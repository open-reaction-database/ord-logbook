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

"""Times the occurrence semi-join against an in-memory table and against Parquet.

Decides whether the occurrence index can become a derived artifact. The semi-join is the
only thing the index is read for, so what it costs over Parquet is what the change costs.

Three shapes, over the same rows:

1. ``memory``   -- the table Corpus._occurrences builds today.
2. ``parquet``  -- one file per path, global_id already in the file. Not a shape an
                   artifact can take, since global_id is corpus-dependent; it isolates
                   the scan cost from the join cost.
3. ``joined``   -- one file per dataset per path holding the dataset-local structure_id,
                   with the offset joined on at read time, keyed by filename exactly as
                   Corpus._pivot_offsets keys a pivot. This is the artifact shape.

Run: python measure_occurrences.py <projections> <structures> <pivots> <workdir>
"""

import logging
import pathlib
import statistics
import sys
import time

from ord_schema.artifacts import pivot
from ord_schema.search import execute, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("measure")

_ROUNDS = 5
# Patterns whose match sets differ in size: the scan is the same either way, but what it
# returns is not, and a semi-join that returns most of the corpus is the harder case.
_PATTERNS = ["c1ccncc1", "[OX2H]", "C(=O)O", "[#6]"]


def _bitmap(corpus: execute.Corpus, pattern: str) -> str:
    """Returns a substructure pattern's match set as the compiler binds it."""
    cursor = corpus._connection.cursor()
    try:
        return corpus._matches(
            cursor,
            query.StructureParameter(
                name="p",
                op="substructure",
                pattern=pattern,
                compound=None,
                threshold=None,
            ),
            lambda name: name,
        )
    finally:
        cursor.close()


def _write(corpus: execute.Corpus, out: pathlib.Path) -> list[str]:
    """Writes both Parquet shapes and publishes the offsets relation; returns the paths."""
    connection = corpus._connection
    written = []
    for path in sorted(execute.INDEXED_PATHS):
        table = pivot.table_name(path)
        flat = out / f"global_{table}.parquet"
        # COPY takes its destination as a literal, not as a bound parameter.
        connection.execute(
            "COPY (SELECT reaction_id, global_id, reaction_role FROM occurrences "
            f"WHERE path = '{path}') TO '{flat}' (FORMAT PARQUET, COMPRESSION zstd)"
        )
        logger.info("wrote %s, %.1f MB", flat.name, flat.stat().st_size / 1e6)

    # The artifact shape. Rows are split back to the dataset they came from and the
    # offset subtracted out, recovering the dataset-local ID a derivation would write.
    bounds = connection.execute(
        "SELECT structure_offset, lead(structure_offset) OVER (ORDER BY structure_offset)"
        ", projection_filename FROM structure_offsets ORDER BY structure_offset"
    ).fetchall()
    for path in sorted(execute.INDEXED_PATHS):
        table = pivot.table_name(path)
        for offset, upper, projected in bounds:
            target = out / table / f"{pathlib.Path(projected).stem}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            bound = "" if upper is None else f" AND global_id < {upper}"
            connection.execute(
                f"COPY (SELECT reaction_id, (global_id - {offset})::UINTEGER "
                "AS structure_id, reaction_role FROM occurrences "
                f"WHERE path = '{path}' AND global_id >= {offset}{bound}) "
                f"TO '{target}' (FORMAT PARQUET, COMPRESSION zstd)"
            )
            written.append((str(target), offset))
    total = sum(f.stat().st_size for f in out.rglob("*/*.parquet"))
    logger.info(
        "artifact-shaped occurrences: %.1f MB over %d files", total / 1e6, len(written)
    )
    connection.execute("DROP TABLE IF EXISTS occurrence_offsets")
    connection.execute(
        "CREATE TABLE occurrence_offsets (occurrence_filename VARCHAR, "
        "structure_offset BIGINT)"
    )
    connection.executemany(
        "INSERT INTO occurrence_offsets VALUES (?, ?)", written
    )
    return written


def main() -> None:
    projections, structures, pivots, workdir = sys.argv[1:5]
    out = pathlib.Path(workdir)
    out.mkdir(parents=True, exist_ok=True)

    opened = time.perf_counter()
    corpus = execute.Corpus(
        projections,
        structures,
        resolver={}.__getitem__,
        pivots_dir=pivots,
        memory_limit="6500MiB",
    )
    logger.info("corpus open and warm in %.1fs", time.perf_counter() - opened)

    _write(corpus, out)

    results: dict[str, list[float]] = {}
    matched: dict[str, int] = {}
    for round_index in range(_ROUNDS):
        for pattern in _PATTERNS:
            blob = _bitmap(corpus, pattern)
            for path in sorted(execute.INDEXED_PATHS):
                table = pivot.table_name(path)
                shapes = {
                    "memory": (
                        "SELECT occurrence.reaction_id FROM occurrences AS occurrence "
                        f"WHERE occurrence.path = '{path}' "
                        "AND get_bit(CAST($p AS BITSTRING), "
                        "occurrence.global_id::INTEGER) = 1"
                    ),
                    "parquet": (
                        "SELECT occurrence.reaction_id FROM read_parquet('"
                        f"{out}/global_{table}.parquet') AS occurrence "
                        "WHERE get_bit(CAST($p AS BITSTRING), "
                        "occurrence.global_id::INTEGER) = 1"
                    ),
                    "joined": (
                        "SELECT o.reaction_id FROM read_parquet('"
                        f"{out}/{table}/*.parquet', filename=true) o "
                        "JOIN occurrence_offsets f "
                        "ON o.filename = f.occurrence_filename "
                        "WHERE get_bit(CAST($p AS BITSTRING), "
                        "(o.structure_id + f.structure_offset)::INTEGER) = 1"
                    ),
                }
                for shape, sql in shapes.items():
                    cursor = corpus._connection.cursor()
                    try:
                        start = time.perf_counter()
                        rows = cursor.execute(sql, {"p": blob}).fetchall()
                        elapsed = time.perf_counter() - start
                    finally:
                        cursor.close()
                    key = f"{shape}|{path}|{pattern}"
                    results.setdefault(key, []).append(elapsed)
                    matched[key] = len(rows)
        logger.info("round %d of %d done", round_index + 1, _ROUNDS)

    print("\nshape    path                                               pattern  med(s)    rows")
    for key in sorted(results, key=lambda k: (k.split("|")[1], k.split("|")[2], k)):
        shape, path, pattern = key.split("|")
        print(
            f"{shape:<8} {path:<50} {pattern:<8} "
            f"{statistics.median(results[key]):>7.3f} {matched[key]:>8}"
        )
    print("\nby shape, median per query summed and maxed over every path and pattern:")
    for shape in ("memory", "parquet", "joined"):
        values = [
            statistics.median(v) for k, v in results.items() if k.startswith(f"{shape}|")
        ]
        print(f"  {shape:<8} sum {sum(values):>7.3f}s  max {max(values):>7.3f}s")
    corpus.close()


if __name__ == "__main__":
    main()
