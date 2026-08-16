# Name-only compounds in the ORD: 865k rows have a name but no structure

- **Date:** 2026-07-11
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** name-only compounds, underivable, derived-smiles, resolvers, opsin, cir, data-quality, ord_20260702

## Question

The ORM derived-SMILES pass generates a SMILES for every compound that has a structural
identifier (or one reconstructable from its identifiers). A large tail of compounds carry only a
**NAME** — no SMILES/INChI/MOLBLOCK — so they never get a derived row and are never structure-
searchable. How many are there, what are they, and how many structures can a name resolver recover
if we skip PubChem (rate limits)?

This came out of [ord-schema #899](https://github.com/open-reaction-database/ord-schema/issues/899)
/ [#900](https://github.com/open-reaction-database/ord-schema/pull/900): the derived pass was
re-attempting these name-only compounds via full message reconstruction on every run. #900 skips
them cheaply; this entry quantifies exactly what is being skipped.

## Summary

- **864,997 name-only rows**, across **52,651 unique names**: 799,989 `ord.compound` rows
  (48,821 unique names) + 65,008 `ord.product_compound` rows (6,833 unique).
- **Name-only ≈ the entire underivable set.** On `ord_20260702`, `ord.compound` has 800,243
  compounds with no derived SMILES; 799,989 of them are name-only. The other ~250 have no name
  either, or a structural identifier RDKit can't parse. So "underivable" and "name-only" are the
  same population to within 0.03%.
- **The distribution is workup/solvent boilerplate, not chemistry.** Inputs are dominated by
  "crude product" (102,272), "hexanes" (42,131), "solution" (40,628), "ice water", "ice", "crude
  material"; products by physical form: "solid" (14,969), "oil", "powder", "foam". A long tail of
  ~30k singletons is real specific compounds someone entered by name without a structure.
- **Structure recovery tops out around 10% of rows** — because most name-only rows are not
  compounds. Combining a hand-curated dictionary with OPSIN resolved **1,646 unique names →
  86,841 rows (10.0%)**: 36 manually-curated solvents/reagents (74,884 rows on their own, 8.7%)
  plus 1,610 systematic IUPAC names from OPSIN (the specific-name tail). The other ~90% of rows
  are workup boilerplate ("crude product", "solution", "ice") and undefined mixtures (eluents,
  petroleum ether) with no single structure.
- **Which resolvers ran, and a reliability warning.** PubChem was skipped (rate limits); NCI/CADD
  CIR (cactus) was down / blocking us (connection-level failures on every request), leaving OPSIN
  (systematic IUPAC only). CIR's brief window before it died also produced *wrong* answers —
  `TEA` → triethanolamine (should be triethylamine), `II` → I₂ (a roman-numeral label read as
  diiodine) — so its 13 results were dropped in favor of the manual dict. Hand-curation is the
  reliable path for the high-frequency abbreviations.

## Method

- **Source:** `ord_20260702`, the completed ORM search database (built with the #890 workup/
  product-measurement fix, #896 per-dataset RDKit scoping, and #900). Read-only over the bastion
  SSM tunnel.
- **Name-only definition:** a compound with a `NAME` identifier and **no** structural identifier,
  where structural = `message_helpers.STRUCTURAL_IDENTIFIER_TYPES` = {SMILES, INChI, MOLBLOCK}.
- **Extraction:** two `\copy` queries over `ord.compound_identifier` (~48.5M rows), one per owning
  foreign key (`compound_id`, `product_compound_id`): the `NAME` values of owners with no
  structural identifier, grouped by value and sorted by frequency. Outputs
  [`name_only_compounds.tsv.gz`](name_only_compounds.tsv.gz)
  and
  [`name_only_product_compounds.tsv`](name_only_product_compounds.tsv)
  (`count⇥name`, header, frequency-sorted).
- **Union + junk filter:** dedup across both files (52,651 unique names), then drop obvious
  non-compounds — process/physical descriptors (mixtures, solutions, residues, color+form phrases
  like "pale yellow oil"), generic class terms ("amine", "ester"), and chromatography eluents
  ("EtOAc hexanes") — with
  [`filter_names.py`](filter_names.py). Kept 46,831,
  skipped 5,820. Real solvents/reagents and systematic names are retained.
- **Automated resolver:** [`run_resolver.py`](run_resolver.py)
  drives `ord_schema.resolvers` with PubChem removed. It is resumable and distinguishes a genuine
  miss (404 / CIR-500) from a transient failure (429/5xx/timeout) so a rate-limit doesn't
  permanently mark a name unresolved. CIR was unreachable, so the effective backend was OPSIN
  (EBI web service), which returned zero rate-limiting over 46,831 names. Results:
  [`resolver_results.tsv.gz`](resolver_results.tsv.gz)
  (`name⇥smiles⇥resolver`).
- **Manual dictionary:** [`manual_resolve.py`](manual_resolve.py)
  hand-maps the frequent single-compound solvents/reagents from the top of the distribution,
  canonicalizing each through RDKit. Generic classes (amine, ester), undefined mixtures (petroleum
  ether, xylenes), supported catalysts (Pd/C), organometallic complexes, and polymers/materials
  are deliberately excluded. Two obvious typos are resolved to the intended reagent (`NaSO4` →
  Na₂SO₄, `Mg2SO4` → MgSO₄).
- **Combined:** manual ∪ OPSIN, manual taking precedence on overlap, CIR dropped:
  [`combined_resolved.tsv`](combined_resolved.tsv)
  (`name⇥smiles⇥source`).

## Findings

Name-only counts on `ord_20260702`:

| Population | Rows | Unique names |
| --- | --- | --- |
| `ord.compound` | 799,989 | 48,821 |
| `ord.product_compound` | 65,008 | 6,833 |
| **Union** | **864,997** | **52,651** |

Most frequent input names / product names:

| count | input name | | count | product name |
| --- | --- | --- | --- | --- |
| 102,272 | crude product | | 14,969 | solid |
| 42,131 | hexanes | | 3,387 | oil |
| 40,628 | solution | | 2,444 | crude product |
| 37,478 | ice water | | 2,056 | product |
| 27,675 | ice | | 1,661 | hydrochloride salt |
| 23,279 | crude material | | 1,364 | powder |

Inputs skew to workup/solvent boilerplate; products skew to physical form.

Head vs tail: the top handful of names cover a large share of the 865k rows (workup/solvent
boilerplate), while 30,203 names (26,336 input + 3,867 product) appear exactly once — specific
compounds entered by name only.

Structure recovery (46,831 candidates after junk filtering):

| Source | Unique names | Notes |
| --- | --- | --- |
| Manual dictionary | 36 | curated solvents/reagents; 74,884 rows (8.7%) on their own |
| OPSIN | 1,610 | systematic IUPAC names; the specific-name tail; 0 rate-limiting |
| NCI/CADD CIR | (13, dropped) | service down; brief-window results included wrong answers (TEA → triethanolamine) |
| PubChem | (skipped) | rate limits |
| **Combined (manual ∪ OPSIN)** | **1,646** | **86,841 rows = 10.0% of all name-only rows** |

The ~90% of rows left unresolved are dominated by non-compounds (crude product, solutions, ice,
mixtures), not by resolver gaps. The ~51k unique names left unresolved are mostly trade/trivial
names (need PubChem or a working CIR) and non-chemical labels.

## Conclusions / next steps

- **#900 already handles the derivation cost** — the derived pass no longer reconstructs these on
  every run. This entry is the inventory of what it skips, not a bug.
- **Recovery is capped by the data, not the tooling.** 90% of name-only rows are non-compounds
  (workup boilerplate, solutions, mixtures) with no structure to recover. The 10% that are real
  compounds are now resolved (`combined_resolved.tsv`): the frequent solvents/reagents by hand, the
  systematic-name tail by OPSIN.
- **Hand-curation beat the automated resolver on the high-value names** — CIR mis-resolved `TEA`
  and `II`. For a small, high-frequency, high-ambiguity set, a curated dictionary is worth more
  than an online lookup.
- **To push recovery higher** would need PubChem or a working CIR for the ~51k trade/trivial names
  OPSIN can't parse — but those are low-count (mostly singletons), so the row-coverage payoff is
  small. Extending the manual dictionary a bit further down the frequency list is the better ROI.
- **Optional backfill:** write the 1,646 resolved SMILES back as identifiers on the corresponding
  compounds, moving ~87k rows into the derivable/searchable set. `combined_resolved.tsv` is ready
  if we decide to.

## References

- ord-schema [#899](https://github.com/open-reaction-database/ord-schema/issues/899) (issue),
  [#900](https://github.com/open-reaction-database/ord-schema/pull/900) (skip reconstruction for
  underivable compounds), and `ord_schema/resolvers.py` (the resolver; PubChem → CIR → OPSIN).
- Assets: [`name_only_compounds.tsv.gz`](name_only_compounds.tsv.gz),
  [`name_only_product_compounds.tsv`](name_only_product_compounds.tsv),
  [`filter_names.py`](filter_names.py),
  [`run_resolver.py`](run_resolver.py),
  [`resolver_results.tsv.gz`](resolver_results.tsv.gz),
  [`manual_resolve.py`](manual_resolve.py),
  [`manual_resolved.tsv`](manual_resolved.tsv),
  [`combined_resolved.tsv`](combined_resolved.tsv).
- Database: `ord_20260702` (Aurora; reached read-only via the bastion SSM tunnel).
