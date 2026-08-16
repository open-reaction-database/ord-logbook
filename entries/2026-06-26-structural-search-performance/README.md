# Structural search performance in the ORD interface

- **Date:** 2026-06-26
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** ord-interface, search, performance, postgres, rdkit, gist
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

Some structural searches in the ORD interface take 20–60+ seconds (or hang) —
benzene as an exact reactant, "products containing a pyridine ring", "similar to
morphine". Is this just a missing timeout, or can we be cleverer about operator
choices, search paths, and fallbacks? In particular: is the slowness caused by
queries falling off the GiST indexes?

## Summary

**The GiST indexes are being used correctly — the operator forms in the code are
already index-friendly — so this is not a wrong-operator bug.** The slowness has three
distinct causes, each needing a different fix, and a missing `statement_timeout` is why
the worst cases hang rather than fail. Measured against the live `ord` database
(~2.4M reactions, ~1.4M `rdkit.mols`) on 2026-06-26.

Operator forms and their indexes (all confirmed used via `EXPLAIN`):

- EXACT: `rdkit.mols.smiles = :smiles` → btree unique `mols_smiles_key`.
- SUBSTRUCTURE/SMARTS: `mol @> :q::mol` → GiST `mol_index`.
- SIMILAR: `morgan_bfp % morganbv_fp(:smiles)` → GiST `morgan_bfp_index`.

The code already filters with the index operators and uses the *function* form
`tanimoto_sml()` only to **score** the already-filtered candidate set — exactly the
right split, because the function form does not use the index.

## Method

Read-only connection to the production Aurora cluster (via the bastion SSM tunnel) and
ran `EXPLAIN (ANALYZE, BUFFERS, TIMING)` on the representative slow queries, plus a
timed end-to-end sweep of the 10-case natural-language eval (`--search`).

Relevant table sizes:

| table | rows |
|---|---|
| `ord.reaction` | 2,428,291 |
| `rdkit.mols` | 1,432,325 |
| `ord.compound` | 17,043,157 |
| `ord.reaction_input` | 9,877,133 |
| `ord.product_compound` | 2,673,037 |

Indexes on `rdkit.mols`: `mols_pkey` (btree id), `mols_smiles_key` (btree unique
smiles), `mol_index` (gist mol), `morgan_bfp_index` (gist), `morgan_sfp_index` (gist).
Join columns are indexed: `ix_ord_compound_rdkit_mol_id`,
`ix_ord_product_compound_rdkit_mol_id`.

## Findings

End-to-end eval sweep (search phase only; translation ~1 s/case, resolution is a
network/cache artifact): **search dominates at ~110 s across 10 cases.** The expensive
cases:

| query | mode | search time | results |
|---|---|---|---|
| benzene as input, yield > 70% | EXACT + yield (INTERSECT) | ~21 s | 1000 (capped) |
| products similar to morphine | SIMILAR | ~22 s | 187 |
| products containing a pyridine ring | SUBSTRUCTURE | >45 s (timed out) | — |
| toluene as input, conversion < 50% | EXACT + conversion | ~47 s | 0 |

### 1. SIMILAR — the GiST index is used but the index scan itself is slow

`morgan_bfp % morganbv_fp(...)` uses `morgan_bfp_index`, but the `Bitmap Index Scan on
morgan_bfp_index` *itself* took **20.4 s** to return ~73 mol rows:

```text
Bitmap Index Scan on morgan_bfp_index (actual time=20363.7..20363.7 rows=73 loops=1)
  Index Cond: (morgan_bfp % '...'::bfp)
Execution Time: 20380.6 ms
```

So the cost is the GiST bfp traversal over 1.4M fingerprints (I/O-bound, cold cache),
not a recheck and not a missing index. Levers: raise the default Tanimoto threshold
(0.5 is permissive), keep the index hot in cache, or a different similarity index.

### 2. SUBSTRUCTURE on common scaffolds — unselective screen, huge recheck

Pyridine substructure on products uses `mol_index` (Bitmap Index Scan with
`Recheck Cond: mol @> 'c1ccncc1'::mol`), but the fingerprint screen is unselective for
a tiny aromatic ring, so the recheck runs subgraph isomorphism on an enormous candidate
set and effectively hangs. `EXPLAIN` without `ANALYZE` shows a cheap-looking plan
(cost ~17,900) — the cost model cannot see the recheck cost. No operator change fixes
this; substructure on a one-ring fragment is inherently a near-scan.

### 3. EXACT on common reagents — high fan-out + cold-cache random I/O

Benzene as an input matches exactly one `rdkit.mols` row (via the btree), but that one
mol fans out to **25,757** compounds/reactions. The single-branch query took **5.5 s**,
almost entirely cold random heap I/O (`I/O Timings: shared read≈9 s` cumulative across
nested-loop index scans). The planner also badly misestimates selectivity
(`rows=12` vs actual `25,757`), which leads it to pick nested loops that are poor once
the branch is combined.

### 4. Query shape: INTERSECT + top-level LIMIT can't bound the work

`run_queries` combines predicates as `INTERSECT` of `SELECT DISTINCT reaction_id`
branches and puts `LIMIT` on top of the whole set operation. Each branch is fully
materialized (sort + unique) before the intersect, so `LIMIT` truncates the final
result but does **not** bound the per-branch index scans. A code comment already
acknowledges this. For benzene + yield > 70%, both branches are huge and fully
materialized before intersecting — hence ~21 s even though the answer is capped at 1000.

## Conclusions / next steps

It is **not** just a timeout, and it is **not** an operator-choice bug (the operators
are already index-optimal). A `statement_timeout` is a mandatory safety net, but the
real wins are in query shape and selectivity.

Items 1 and 2 below are **implemented** in
[ord-interface#205](https://github.com/open-reaction-database/ord-interface/pull/205);
items 3–5 remain as follow-ups.

1. **Add a `statement_timeout`** in `get_cursor` (there was none) so no query runs
   away; surface a graceful "query too broad — add constraints" instead of a hang.
   *(Done in #205: default 20 s via `ORD_INTERFACE_STATEMENT_TIMEOUT_MS`; the
   resulting `QueryCanceled` maps to a 400, and the async task path records the
   error so it is reported rather than polling forever.)*
2. **Rewrite multi-predicate queries from INTERSECT-of-DISTINCT to semi-joins / EXISTS
   driven from the most selective predicate.** Filter on yield/conversion/dataset
   first, then apply the expensive structural recheck only to survivors. This attacks
   benzene + yield (~21 s) and any "broad structure + selective filter" combination,
   and lets `LIMIT` actually bound the structural work.
   *(Done in #205: each predicate is now an `EXISTS` over `ord.reaction`, combined
   with `AND` under one `LIMIT`. Live-DB measurements: benzene EXACT + yield > 70%
   ~25 s → ~10 s; morphine SIMILAR ~22 s → ~1 s.)*
3. **Selectivity heuristic for lone broad structural searches.** For tiny aromatic
   fragments (benzene/pyridine substructure), estimate candidate count cheaply and
   refuse / require a co-constraint / warn rather than scanning. For the NL `/ask`
   path, also steer the model away from standalone SUBSTRUCTURE on small fragments and
   toward EXACT.
4. **SIMILAR tuning.** Raise the default Tanimoto threshold and keep `morgan_bfp_index`
   hot; consider an alternative similarity index if 20 s scans persist warm.
5. **Cache/warm storage.** Much of the EXACT cost was cold random I/O; a warm cache or
   faster storage helps, but is a mitigation, not an algorithmic fix.

This applies equally to the structured `/search` API and the natural-language `/ask`
path, since both compile to the same `queries.py` engine.

## References

- Implementation of fixes 1 and 2:
  [ord-interface#205](https://github.com/open-reaction-database/ord-interface/pull/205).
- Search engine: `ord-interface` `ord_interface/api/queries.py`
  (`ReactionComponentQuery`, `run_queries`, `_rank_by_similarity`).
- Natural-language path that surfaced these cases:
  `2026-06-26-natural-language-query-interface.md`.
- RDKit PostgreSQL cartridge (operator vs. function forms and GiST indexes):
  <https://www.rdkit.org/docs/Cartridge.html>.
