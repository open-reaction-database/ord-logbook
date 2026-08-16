"""Split the union names into plausible-compound vs obvious-junk.

Junk = process/physical descriptors that are not chemical entities (crude product, solutions,
mixtures, residues, color+physical-form phrases like "pale yellow oil"). Real solvents/reagents
(hexanes, water, THF) and systematic/trivial names are kept.
"""

import re
import sys

UNION, KEEP, SKIP = sys.argv[1], sys.argv[2], sys.argv[3]

# Any of these as a whole word => a process/mixture/description, not a single compound.
JUNK_WORDS = re.compile(
    r"\b("
    r"mixture|solution|crude|residue|filtrate|slurry|suspension|precipitate|supernatant|"
    r"washings?|eluent|eluant|distillate|condensate|sublimate|workup|work-?up|"
    r"layer|phase|organics"
    r")\b",
    re.I,
)
# "mother liquor", "title compound/product" as phrases.
JUNK_PHRASES = re.compile(r"\b(mother liquor|title (compound|product)|reaction)\b", re.I)

# The whole name is just an (optional color) + physical form.
_QUAL = r"(?:pale|light|dark|deep|bright|very|off[- ]?white|pale[- ]?yellow|semi[- ]?)"
_COLOR = (
    r"(?:white|yellow|colou?rless|clear|brown|orange|red|green|blue|black|tan|beige|amber|"
    r"gold(?:en)?|pink|purple|violet|grey|gray|cream|dark)"
)
_FORM = (
    r"(?:solid|oil|foam|gum|powder|syrup|wax|paste|semi-?solid|liquid|crystal(?:s|line)?|"
    r"material|film|resin|glass|mass|product|needles?|plates?|granules?|residue|slush|slurry)"
)
COLOR_FORM = re.compile(rf"^(?:{_QUAL}\s+)*(?:{_COLOR}\s+)*{_FORM}$", re.I)

EXACT_JUNK = {
    "product", "desired product", "the product", "this material", "material", "reaction",
    "ice", "ice water", "ice-water", "ice/water", "gas", "liquid", "distillate", "compound",
    "the title compound", "brine",  # brine is a saturated-salt solution, not a single compound
    # Generic functional-class / role terms that name no specific structure.
    "amine", "amide", "ester", "acid", "alcohol", "ketone", "aldehyde", "ether", "base",
    "acid chloride", "acyl chloride", "alkene", "alkyne", "arene", "halide", "aryl halide",
    "salt", "hydrochloride salt", "hydrochloride", "the salt", "free base", "catalyst",
    "reagent", "grignard reagent", "grignard", "starting material", "sm", "substrate",
    "byproduct", "by-product", "impurity", "intermediate", "desired compound",
    "target compound", "the compound", "this compound", "product compound", "diamine", "diol",
    "none", "n/a", "na", "nan", "null", "unknown", "same", "as above", "see text",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "several", "various",
    "solvent", "solvents", "stainless steel", "expected product", "methyl ester", "ethyl ester",
    "molecular sieves", "sieves", "celite", "glass", "membrane", "the solvent",
}

# Chromatography eluents: two solvents juxtaposed (e.g. "EtOAc hexanes"); not a single compound.
_ELUENT = re.compile(
    r"(hexane|petroleum ether|pet\.? ether|pet ether)", re.I
)
_ELUENT_PARTNER = re.compile(
    r"(acetate|etoac|\bether\b|\bdcm\b|methanol|\bmeoh\b|ethanol|\betoh\b)", re.I
)


def _is_eluent(low: str) -> bool:
    # "petroleum ether" alone contains "ether"; require a second, distinct solvent cue.
    partner = _ELUENT_PARTNER.sub(
        lambda m: "" if m.group(0).lower() == "ether" and "petroleum ether" in low else m.group(0),
        low,
    )
    has_sep = re.search(r"[\s/\-]", low.strip())
    return bool(_ELUENT.search(low)) and bool(_ELUENT_PARTNER.search(partner)) and bool(has_sep)


def is_junk(name: str) -> bool:
    low = name.strip().lower()
    if not low or low in EXACT_JUNK:
        return True
    if not re.search(r"[a-z]", low):  # no letters (pure numbers/symbols)
        return True
    if JUNK_WORDS.search(low) or JUNK_PHRASES.search(low):
        return True
    if COLOR_FORM.match(low):
        return True
    if _is_eluent(low):
        return True
    return False


kept = skipped = 0
with open(UNION) as src, open(KEEP, "w") as keep, open(SKIP, "w") as skip:
    for line in src:
        name = line.rstrip("\n")
        if not name:
            continue
        if is_junk(name):
            skip.write(name + "\n")
            skipped += 1
        else:
            keep.write(name + "\n")
            kept += 1
print(f"kept={kept} skipped={skipped} total={kept + skipped}")
