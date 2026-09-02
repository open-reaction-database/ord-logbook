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

"""Prototypes the SQL-deduplicated library build and times each part of it."""

import argparse, array, json, logging, sys, time
from rdkit import DataStructs
from rdkit.Chem import rdSubstructLibrary
from ord_schema.artifacts import structures
from ord_schema.search import execute

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)


def main(args):
    """Builds the library from one row per distinct SMILES and reports the split."""
    with execute.Corpus(
        args.projections, args.structures, resolver={}.__getitem__,
        occurrences_dir=args.occurrences_dir, warm=False,
        memory_limit=args.memory_limit,
    ) as corpus:
        cursor = corpus._connection.cursor()  # noqa: SLF001
        report = {}
        whole = time.perf_counter()

        start = time.perf_counter()
        distinct = cursor.execute(
            "SELECT any_value(mol_binary) AS mol_binary, "
            "       any_value(pattern_fp) AS pattern_fp "
            "FROM corpus_structures GROUP BY smiles ORDER BY smiles"
        ).fetch_arrow_table()
        report["distinct_query"] = time.perf_counter() - start

        start = time.perf_counter()
        blobs = distinct.column("mol_binary").to_pylist()
        prints = distinct.column("pattern_fp").to_pylist()
        report["distinct_to_pylist"] = time.perf_counter() - start

        start = time.perf_counter()
        molecules = rdSubstructLibrary.CachedMolHolder()
        patterns = rdSubstructLibrary.PatternHolder(structures.PATTERN_FP_SIZE)
        unparseable = execute._UNPARSEABLE  # noqa: SLF001
        no_bits = execute._NO_BITS  # noqa: SLF001
        for blob, fingerprint in zip(blobs, prints, strict=True):
            if blob is None:
                molecules.AddBinary(unparseable)
                patterns.AddFingerprint(no_bits)
            else:
                molecules.AddBinary(blob)
                patterns.AddFingerprint(DataStructs.CreateFromBinaryText(fingerprint))
        report["rdkit_adds"] = time.perf_counter() - start

        start = time.perf_counter()
        library = rdSubstructLibrary.SubstructLibrary(molecules, patterns)
        report["library_ctor"] = time.perf_counter() - start

        start = time.perf_counter()
        mapping = cursor.execute(
            "SELECT (dense_rank() OVER (ORDER BY smiles) - 1)::UINTEGER AS entry "
            "FROM corpus_structures ORDER BY global_id"
        ).fetch_arrow_table()
        report["mapping_query"] = time.perf_counter() - start

        start = time.perf_counter()
        column = mapping.column("entry").combine_chunks()
        entry_of = array.array("I")
        entry_of.frombytes(column.buffers()[1][: 4 * len(column)])
        report["mapping_to_array"] = time.perf_counter() - start
        report["entry_of_len"] = len(entry_of)

        start = time.perf_counter()
        members, starts = execute._group(entry_of, len(library))  # noqa: SLF001
        report["group"] = time.perf_counter() - start

        report["total"] = time.perf_counter() - whole
        report["entries"] = len(library)

        # The same answer the current build produces, or the prototype is worthless.
        reference_entry_of = array.array("I")
        entries = {}
        for (smiles,) in cursor.execute(
            "SELECT smiles FROM corpus_structures ORDER BY global_id"
        ).fetchall():
            reference_entry_of.append(entries.setdefault(smiles, len(entries)))
        report["entry_count_matches"] = len(entries) == len(library)
        # Numbering differs (SMILES order versus first-seen), so compare the partition
        # rather than the labels: two structures share an entry iff they share a SMILES.
        report["partition_matches"] = _same_partition(entry_of, reference_entry_of)
        cursor.close()
    print(json.dumps(report, indent=2))


def _same_partition(left: array.array, right: array.array) -> bool:
    """Returns whether two labelings group their positions identically."""
    seen: dict[int, int] = {}
    for a, b in zip(left, right, strict=True):
        if seen.setdefault(a, b) != b:
            return False
    return len(seen) == len(set(right))


def parse_args(argv=None):
    """Parses command-line arguments."""
    p = argparse.ArgumentParser()
    p.add_argument("--projections", required=True)
    p.add_argument("--structures", required=True)
    p.add_argument("--occurrences_dir", required=True)
    p.add_argument("--memory_limit", default="6500MiB")
    return p.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
