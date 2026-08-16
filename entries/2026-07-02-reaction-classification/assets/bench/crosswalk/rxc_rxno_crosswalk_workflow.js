export const meta = {
  name: 'rxc-rxno-crosswalk',
  description: 'LLM crosswalk: map 5,631 ReactionClassifier reaction descriptions to RXNO ids (47 batches)',
  phases: [{ title: 'Map', detail: 'one agent per batch of 120 descriptions -> most-specific RXNO id or null' }],
}

// Absolute path to the crosswalk_work directory written by prep_llm_crosswalk.py.
// Agents read vocab.txt and batch_*.json from it and write out_*.json back.
const DIR = args?.dir
if (!DIR) throw new Error('pass {dir: "/abs/path/to/crosswalk_work"} as args')
const NB = 47

phase('Map')

const pad = (b) => String(b).padStart(3, '0')
const prompt = (b) => `You are building a crosswalk from ReactionClassifier (RXC) reaction classes to the RXNO Name Reaction Ontology.

Read these two files with the Read tool:
1. ${DIR}/vocab.txt — the RXNO vocabulary, one term per line: \`RXNO:ID | name | syn: synonyms\`. These RXNO ids are the ONLY valid targets.
2. ${DIR}/batch_${pad(b)}.json — a JSON array of RXC classes: [{"i": <int>, "name": "<pipe-separated reaction description, general -> specific>"}].

For EACH class, pick the single MOST-SPECIFIC RXNO id whose meaning matches the reaction. Eponyms (Suzuki, Mannich, Buchwald, Gabriel, Wohl-Ziegler, ...) may appear in any pipe segment; later segments are more specific.

Rules:
- Prefer a specific named reaction over a broad umbrella term (e.g. use "Suzuki-Miyaura coupling" not "carbon-carbon coupling reaction"; use a broad term only if nothing specific fits).
- Use rxno_id = null when NO RXNO term genuinely matches. RXNO omits many generic protections, deprotections, oxidations, reductions, and functional-group interconversions — return null rather than forcing a bad match.
- Never invent an id; every id you output must appear verbatim in vocab.txt.
- confidence: "high" = clearly the correct specific term; "medium" = right family but coarser/uncertain; "low" = weak guess.

Then use the Write tool to write your answer to EXACTLY this path: ${DIR}/out_${pad(b)}.json
Content must be a compact JSON array with one object per class (include EVERY class in the batch):
[{"i": <same i>, "rxno_id": "RXNO:0000140" or null, "confidence": "high"}]

After writing, return only the text: wrote <count>`

const res = await parallel(
  Array.from({ length: NB }, (_, b) => () =>
    agent(prompt(b), { label: `batch ${pad(b)}`, phase: 'Map', agentType: 'general-purpose', model: 'sonnet', effort: 'medium' })
  )
)

return { batches: res.length, summaries: res.map((r, b) => `${pad(b)}: ${r || 'FAILED'}`) }
