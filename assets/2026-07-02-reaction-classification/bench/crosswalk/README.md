# ReactionClassifier → RXNO crosswalk

Scopes and drafts a map from ReactionClassifier's private taxonomy (6,926
operational classes) to the RXNO Name Reaction Ontology. See the entry's
"Mapping ReactionClassifier → RXNO" section for results and interpretation.

## Files

| File | What |
|---|---|
| `scope_rxno.py` | String/synonym baseline matcher + coverage report (RXNO + MOP) |
| `prep_llm_crosswalk.py` | Dedupe to distinct reaction descriptions, write RXNO vocab + agent batch files |
| `rxc_rxno_crosswalk_workflow.js` | 47-agent LLM crosswalk (one judgment per description) |
| `aggregate_crosswalk.py` | Join agent outputs → per-class map + coverage report |
| `rxc_rxno_crosswalk_llm.json` | **The draft map**: `{RXC code: {rxno, rxno_name, conf}}` (unaudited) |

## Inputs to regenerate

`rxc_classes.json` (2.3 MB, not committed) — dump the 6,926 class names from the
installed `reactionclassifier` package:

```python
import json
from importlib import resources
from reactionclassifier import full_class_name
D = resources.files("reactionclassifier.data")
lm = json.loads(D.joinpath("gate/label_map.json").read_text())
tax = json.loads(D.joinpath("taxonomy.json").read_text())
codes = sorted({str(v) for v in lm.values() if not str(v).startswith("CONFLICT")})
out = [{"code": c, "full": full_class_name(c), "leaf": tax.get(c),
        "segs": [tax[".".join(c.split(".")[:i])] for i in range(2, c.count(".") + 2)
                 if ".".join(c.split(".")[:i]) in tax]} for c in codes]
json.dump(out, open("rxc_classes.json", "w"))
```

`rxno.obo` / `mop.obo` — from the RSC ontology repo:

```bash
curl -sSLO https://raw.githubusercontent.com/rsc-ontologies/rxno/master/rxno.obo
curl -sSLO https://raw.githubusercontent.com/rsc-ontologies/rxno/master/mop.obo
```

## Reproduce

```bash
python scope_rxno.py                       # string-match baseline (writes rxc_rxno_crosswalk.json)
python prep_llm_crosswalk.py               # writes crosswalk_work/{vocab.txt, batch_*.json}
# run rxc_rxno_crosswalk_workflow.js via the Workflow tool, passing the absolute
# path as args: {"dir": "$PWD/crosswalk_work"}  -> crosswalk_work/out_*.json
python aggregate_crosswalk.py              # writes rxc_rxno_crosswalk_llm.json + report
```

## Headline

| Coverage (of 6,926 classes) | string-match | LLM pass |
|---|---|---|
| any RXNO id | 51% | 50% |
| specific (non-umbrella) | 15% | 40% |
| RXNO recall | 116/653 | 243/653 |
| ORD-weighted specific | 7% | 38% |

~48% of ORD reactions have **no** RXNO term (generic transforms → MOP or absent);
that is RXNO's named-reaction-only ceiling, not a matcher limit. The map is
**unaudited** — chemist review needed before production use.
