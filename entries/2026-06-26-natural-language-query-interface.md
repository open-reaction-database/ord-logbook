# Natural-language query interface for the ORD

- **Date:** 2026-06-26
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** ord-interface, search, llm, natural-language, claude, ux

## Question

Can we give the ORD web interface a natural-language search box — e.g. "find
reactions for synthesizing ibuprofen" or "find reactions using benzene as an
input with yield greater than 70%" — that understands chemical intent rather
than doing keyword/full-text matching?

## Summary

**Yes, and it's a thin additive layer — no ORM or schema changes.** The existing
search backend (`ord-interface/ord_interface/api/queries.py`) already exposes a
validated, GiST-index-accelerated structured query language: per-component
`pattern × Target{INPUT,OUTPUT} × MatchMode{EXACT,SIMILAR,SUBSTRUCTURE,SMARTS}`,
plus yield/conversion ranges, DOI, dataset ID, and reaction SMARTS, AND-combined
via `INTERSECT`. The NL feature's only job is to translate a sentence into that
existing `QueryParams` shape — **text-to-tool-call, not text-to-SQL**.

Design decisions that keep it reliable and performant:

1. **The LLM emits a structured query (a tool call), never SQL.** It stays on the
   existing index-accelerated paths; no injection risk; queries.py's RDKit
   parsing validates patterns for free.
2. **The LLM never invents SMILES.** Compound names ("ibuprofen", "benzene") are
   resolved by a tool backed by the existing `ord_schema.resolvers.resolve_names`
   / `_pubchem_resolve` (PubChem). LLMs are unreliable at SMILES; the resolver is
   deterministic and already in the codebase.
3. **Execution is unchanged** — the translated query is handed to the existing
   `run_queries` / Redis task path. New surface is one endpoint.

Search latency is unaffected (same GiST paths); added latency is one LLM call
(~sub-second–2 s with Haiku) plus name resolution (network, cache it).

## Method

Architecture (three layers over the existing engine):

```text
"reactions using benzene as input, yield >70%"
    │  Claude (Haiku 4.5) + tool schema mirroring QueryParams
    ▼  {components:[{name:"benzene", target:INPUT, mode:SUBSTRUCTURE}], min_yield:70}
    │  resolve_names()  →  benzene → c1ccccc1   (PubChem, cached)
    ▼  existing run_queries()  →  GiST-indexed search (unchanged)
    reaction_ids → fetch_reactions → render
```

Key reuse points already in the tree:

- Structured query + execution: `ord-interface/ord_interface/api/queries.py`
  (`ReactionComponentQuery`, `run_queries`, `fetch_reactions`).
- Task/poll infra: `ord-interface/ord_interface/api/search.py` (`QueryParams`,
  Redis submit/fetch).
- Name → SMILES: `ord-schema/ord_schema/resolvers.py`
  (`resolve_names`, `_pubchem_resolve`).

Semantic mappings the LLM owns (no parser can do these):

- "synthesizing X" → X as `OUTPUT`; "using X as input" → X as `INPUT`.
- "yield greater than 70%" → `min_yield=70`.
- "like X" / "similar to X" → `SIMILAR`.

Model: Claude Haiku 4.5 with tool use / JSON-schema-constrained output (the task
is constrained and well-specified). Step up to Sonnet 4.6 only for multi-step
disambiguation or conversational refinement.

## Findings

**Translation accuracy: 10/10 (100%) on the first eval set, with Haiku 4.5.** A
10-case eval (`nl_query_eval_cases.json`) covering OUTPUT/INPUT roles, EXACT/SIMILAR/
SUBSTRUCTURE modes, yield/conversion filters, and multi-component queries passes every
case, including an over-extraction check (the model must leave unrequested numeric
filters null). The runner (`nl_query_eval.py`, `--search`) also executes each query
against the live DB to flag zero-result translations.

**Name resolution is the live bottleneck, not translation.** Exercising `--search`
against the production `ord` database surfaced that `ord_schema.resolvers.resolve_name`
is throttled hard by PubChem (HTTP 503 `PUGREST.ServerBusy`) for *every* common name
(benzene, ibuprofen, aspirin, ...), and OPSIN 404s on trivial/trade names (it only does
systematic IUPAC nomenclature — e.g. "aspirin" fails but "acetylsalicylic acid" works).
This is the motivation for the resolver-caching (landed) and local-table (planned) work
below.

Latency and resolver hit rate in production are still TBD. The design Q&A below was
settled during the working session.

### Cost per query

Each NL search is **one** model call (translation); name resolution and search add
no model cost. A call is roughly **~1.1K input tokens** (system prompt + the
`build_query` tool's JSON schema + the question) and **~150 output tokens** (the
single structured tool call). At current pricing:

| Model | $/MTok in / out | ~Per query | ~Per 1K queries | ~Per 10K queries |
|-------|-----------------|-----------|-----------------|------------------|
| Claude Haiku 4.5 (default) | $1 / $5 | ~$0.002 | ~$1.85 | ~$19 |
| Claude Sonnet 4.6 (upgrade) | $3 / $15 | ~$0.006 | ~$5.55 | ~$56 |

Notes:

- **Prompt caching doesn't help here.** The stable prefix (~1K tokens) is below
  both models' minimum cacheable prefix (Haiku 4.5: 4,096 tokens; Sonnet 4.6:
  2,048), so `cache_control` would never engage. Not worth padding the prompt to
  reach the threshold — the per-call cost is already sub-cent on Haiku.
- **Name resolution is free** (PubChem/OPSIN network calls); cache resolutions to
  cut latency, not cost.
- Dominant cost driver is call volume, which is why rate limiting (below) matters
  more for cost control than model choice.

### Abuse prevention and account isolation (Q&A)

**Can the agent be abused for unrelated tool use / off-ORD tasks?**
Structurally, no. The model is invoked with a **single forced tool call**
(`tool_choice: {type: "tool", name: "build_query"}`) whose only output is a
validated `QueryParams` object. There is no agent loop, no bash, no web access, no
second tool — the model *cannot* do anything but fill out an ORD search form. The
output is further validated by Pydantic + RDKit before it touches the database, and
the DB connection is already read-only (`set_read_only(True)`). The residual
surface is narrow: an off-topic prompt ("write me a poem", a prompt-injection
attempt) wastes one cheap model call and returns an empty/again-validated query, not
arbitrary behavior.

**Do all model calls go through an ORD-specific account?**
Yes — and they should be isolated deliberately. Calls are server-side only, using
`ANTHROPIC_API_KEY` from the server environment; the key never reaches the browser,
so every call bills to whatever Anthropic org/workspace provisions that key.
Recommendation: create a **dedicated Anthropic workspace** for this feature with its
own key and a **hard spend limit** — that cap is the ultimate backstop (requests
start failing gracefully once hit, rather than running up an unbounded bill).

**Can we rate limit by IP?**
Yes, two complementary layers:

1. **App-level**, keyed by client IP, backed by the **Redis we already run** for the
   search task queue (e.g. a token-bucket via `slowapi`/`limits`). Must read the
   real client IP from `X-Forwarded-For` (behind the load balancer), not the socket
   peer.
2. **Edge-level** (more robust against distributed abuse): an **AWS WAF rate-based
   rule** per IP on the ALB/CloudFront in front of the API, offloading the work from
   the app.

IP limiting is imperfect (shared NATs, proxies), so pair a generous per-IP limit
with the per-workspace spend cap. Also **cache identical NL queries** in Redis so
repeated/abusive identical questions don't each cost a call.

## Conclusions / next steps

Phased plan:

- **Phase 1 — code landed (unverified against live DB).** Single structured-output
  Claude call → `QueryParams`, reusing `resolve_name` for entity resolution, exposed
  via a new `/api/nl_query` endpoint that dispatches into the existing search path,
  plus a dedicated **/ask** page in the web app (separate from `/search`) that shows
  the generated structured query for transparency. Covers both example questions.
  See the Handoff section below for exactly what was built and what remains.
- **Phase 2.** Agentic loop (resolve → search → inspect → refine) for
  disambiguation ("ibuprofen vs. ibuprofen sodium?") and multi-turn follow-ups
  ("now drop the ones using palladium").
- **Phase 3.** Reaction-level NL ("reductive amination reactions") → reaction
  SMARTS against `rdkit.reactions`. Needs a named-reaction → SMARTS template
  library; the transformation search itself already exists (`ReactionSmartsQuery`).

Guardrails to carry through all phases:

1. Always display the generated structured query (scientific transparency —
   chemists must be able to trust and correct it).
2. On zero results, have the model propose relaxations (drop yield filter,
   `EXACT` → `SUBSTRUCTURE`).

## Handoff to ord-interface

Phase 1 was implemented in the `ord-interface` working tree (currently uncommitted
on `main` — branch before committing). Summary for an agent picking this up.

**Backend (new):** `ord_interface/api/nl_query.py`

- `translate(query, client)` — forced `build_query` tool call → `NLQuery` (Pydantic
  schema mirroring `QueryParams`). Model from `ORD_NL_QUERY_MODEL`, default
  `claude-haiku-4-5`.
- `build_query_params(nl_query)` (async) → `(QueryParams, [ResolvedComponent])`.
  Resolution: SMARTS passes through; otherwise canonicalize as SMILES, else cached
  `ord_schema.resolvers.resolve_name("name", …)` (PubChem/OPSIN) run in a thread.
- `GET /api/nl_query?q=...` → `{query, interpretation, resolved_components, results}`;
  dispatches through the existing `run_query`. Returns 503 if `ANTHROPIC_API_KEY`
  unset or the model is unreachable, 429 if the model is rate limited, 422 on an
  unresolvable compound, 502 if the model returns no tool call.
- System prompt lives in `nl_query_prompt.md` (shipped via package-data).
- Wired in `api/main.py`; `anthropic` added to `pyproject.toml`.
- Tests: `nl_query_test.py` (translation, error mapping, response + resolver cache)
  and `nl_query_eval_test.py` (eval scoring) — 18 unit tests, all stubbed (no
  network/DB/key). Eval: `nl_query_eval.py` + `nl_query_eval_cases.json`. `ruff` +
  `ty` clean.

**Frontend (new):** a separate **/ask** page (not the `/search` page)

- `app/src/views/nl-search/MainNLSearch.tsx` (+ `.scss`) — text box, example chips,
  an "Interpreted as:" panel (roles, modes, resolved SMILES, resolver), reuses
  `SearchResults`. Query lives in `?q=` for shareable URLs.
- `app/src/hooks/useNLQuery.ts` — calls `/api/nl_query`, deserializes result protos
  like `useSearchTask`.
- Types in `app/src/types/search.ts`; route in `App.tsx` (`/ask`); nav link
  ("Ask") in `components/HeaderNav.tsx`. `tsc` + `eslint` clean.

**Production hardening — landed in a second session (branch `nl-query-production`):**

1. **Resilience — done.** `translate()` maps `anthropic.RateLimitError` → 429 and any
   other `anthropic.APIError` (connection/server/overload/auth) → 503, so the UI
   degrades gracefully instead of 500ing.
2. **Redis response cache — done.** Identical `q` (keyed by model + a `CACHE_VERSION`)
   is served from the existing Redis with a 1h TTL; reads/writes are best-effort, so a
   Redis outage falls back to a live translation rather than failing.
3. **Redis resolver cache — done.** Name → SMILES resolutions are cached separately
   (30-day TTL, keyed by normalized name) and shared across *different* questions that
   mention the same compound — the self-healing write-back layer that spares PubChem
   repeated lookups. Resolution was made async; the blocking PubChem/OPSIN call runs in
   a thread, and resolution failures are *not* cached (a transient 503 must not poison
   the cache).
4. **Prompt → markdown — done.** `SYSTEM_PROMPT` now loads from `nl_query_prompt.md`
   (shipped via `[tool.setuptools.package-data]`) so it reads as plain markdown and is
   editable without Python string escaping.
5. **Eval set — done.** `nl_query_eval_cases.json` (10 cases) + `nl_query_eval.py`
   runner; 100% translation accuracy (see Findings). Tune `nl_query_prompt.md` and the
   EXACT-vs-SUBSTRUCTURE default from future eval results.

**Still remaining:**

1. **Rate limiting** per IP (Redis-backed app layer and/or AWS WAF) — see the abuse
   section above. (Deferred; not selected this session.)
2. **Dedicated Anthropic workspace + spend limit** for `ANTHROPIC_API_KEY`. (Workspace
   created for the ORD org; set a hard spend cap.)
3. Deploy config: ensure `ANTHROPIC_API_KEY` is set in the API environment.
4. **Layered offline name resolver (layer 1)** — see next section.

## Planned: layered offline name resolver

Caching (above) is the self-healing fallback layer; the missing piece is an
**offline, local-first name → SMILES table** so the throttling-prone common names never
hit PubChem in the first place. Decision (this session): **ship caching now, add a local
PubChem-derived table later if throttling persists in production.** The owner is also
adding a separate resolver of their own.

Target architecture (local-first):

1. **Local table** — normalized `name → SMILES` lookup (SQLite/dict). Handles the
   common/trivial/trade names (aspirin, ibuprofen, palladium acetate) that throttle on
   PubChem today. **This is the new piece** — `ord_schema/resolvers.py` ships no local
   dictionary; it calls PubChem REST then OPSIN, nothing offline-first.
2. **OPSIN** (`py2opsin`, MIT, already available via `ord-schema`; needs Java 8+) —
   algorithmic fallback for *systematic IUPAC* names not in the table.
3. **PubChem PUG-REST** — last resort on a miss, with write-back into the cache/table
   (the Redis resolver cache already does the write-back).

Source options researched (2026-06-26), by license posture:

- **PubChem `Drug-Names.tsv.gz`** (~837 KB, **public domain**) joined to `CID-SMILES.gz`
  (~1.4 GB) → covers exactly the drug/reagent names that throttle. Cleanest license for
  targeted coverage; build/join at deploy and ship a slim index. **Recommended seed when
  this is picked up.** Scale to full `CID-Synonym-filtered.gz` (~918 MB) for max hit rate.
- **Global Chem `global_chem.tsv`** (521 KB, 3,354 common names, **MPL-2.0** — file-level
  copyleft, mild flag) + **ORDerly `solvents.csv`** (615 solvents, **MIT**) — tiny,
  zero-build vendored files for an immediate start.
- **Wikidata** (~1.35M names+aliases, **CC0**, ~20–60 MB) — broadest clean-license
  backbone; **ChEBI** (CC BY 4.0) and **EPA DSSTox** (public domain) enrich drug/INN/
  brand names.
- **Avoid for redistribution:** ChEMBL (CC BY-SA copyleft), DrugBank full + CAS Common
  Chemistry (CC BY-NC), and any unlicensed GitHub dumps.

No pip package ships an offline trivial-name dictionary (pubchempy/cirpy/chemspipy are
online; RDKit has no name parsing), so the local layer must be vendored or built.
Normalize keys (lowercase, strip whitespace/salts) on both ingest and lookup.

## References

- `ord-interface` search backend: `ord_interface/api/queries.py`,
  `ord_interface/api/search.py`.
- Name resolution: `ord-schema` `ord_schema/resolvers.py`.
- Design discussion: ord-schema working session 2026-06-26.
