# Copyright 2026 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Times a similarity screen over the whole corpus, and says what the popcount band buys.

Finding 6 of the artifact and search path review: similarity is the one structure
predicate with no acceleration beyond the band the threshold implies, and it had never
been measured at corpus scale. This measures the screen itself rather than a whole
search, since the screen is the part nothing accelerates.
"""

import argparse
import json
import logging
import math
import sys
import time

from rdkit import DataStructs

from ord_schema.artifacts import structures
from ord_schema.search import execute, query

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# Spanning the range of query sizes: a solvent, a reagent, a drug-like molecule, and one
# large enough that its band covers most of the corpus.
QUERIES = {
    "pyridine": "c1ccncc1",
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "ibuprofen": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
    "atorvastatin": (
        "CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CC[C@@H](O)C[C@@H](O)CC(=O)O"
    ),
}
THRESHOLDS = (0.4, 0.6, 0.8)


def _band(smiles: str, threshold: float) -> tuple[int, int, int]:
    """Returns the query's popcount and the band a threshold implies."""
    molecule = execute.Chem.MolFromSmiles(smiles)
    fingerprint = structures.morgan_fingerprint(molecule)
    popcount = fingerprint.GetNumOnBits()
    return popcount, math.ceil(threshold * popcount), math.floor(popcount / threshold)


def main(args: argparse.Namespace) -> None:
    """Opens the corpus and times each query at each threshold."""
    with execute.Corpus(
        args.projections,
        args.structures,
        resolver={}.__getitem__,
        occurrences_dir=args.occurrences_dir,
        require_occurrences=True,
        warm=False,
        memory_limit=args.memory_limit,
    ) as corpus:
        cursor = corpus._connection.cursor()  # noqa: SLF001
        total = cursor.execute(
            "SELECT count(*) FROM corpus_structures WHERE morgan_fp IS NOT NULL"
        ).fetchone()[0]
        results = []
        for name, smiles in QUERIES.items():
            for threshold in THRESHOLDS:
                popcount, low, high = _band(smiles, threshold)
                banded = cursor.execute(
                    "SELECT count(*) FROM corpus_structures WHERE morgan_fp IS NOT NULL "
                    "AND morgan_popcount BETWEEN $lo AND $hi",
                    {"lo": low, "hi": high},
                ).fetchone()[0]
                parameter = query.StructureParameter(
                    name="p", op="similar", pattern=smiles, compound=None,
                    threshold=threshold,
                )
                # Three rounds, median, on a cold cache each time -- _similarity_ids
                # does no caching of its own, so every call is the full screen.
                timings = []
                for _ in range(3):
                    start = time.perf_counter()
                    matched = corpus._similarity_ids(  # noqa: SLF001
                        cursor, parameter, {}.__getitem__
                    )
                    timings.append(time.perf_counter() - start)
                results.append(
                    {
                        "query": name,
                        "threshold": threshold,
                        "query_popcount": popcount,
                        "band": [low, high],
                        "banded": banded,
                        "banded_fraction": banded / total,
                        "matched": len(matched),
                        "seconds": sorted(timings)[1],
                    }
                )
                print(json.dumps(results[-1]), flush=True)
        cursor.close()
    print(json.dumps({"total_fingerprinted": total, "results": results}))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--projections", required=True)
    parser.add_argument("--structures", required=True)
    parser.add_argument("--occurrences_dir", required=True)
    parser.add_argument("--memory_limit", default="6500MiB")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
