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

"""Where the bytes sit inside a pivot's *pruned* element, read from the footers.

A pivot over a wide level costs nearly what the level's whole column costs, so pruning
it further only pays if the weight is concentrated somewhere a pivot could drop. The
footers already say how large every leaf is, per file and per row group, without
decoding a byte of column data.

The leaves that matter are the ones ``pivot._prune`` keeps: those reached from the level
without crossing another repeated hop. A leaf below one belongs to a deeper level and
is already absent, so counting it here would credit pruning with bytes it never held.

Sizes are the uncompressed Parquet figures, which is a proxy for what a level costs in
memory rather than the figure itself: DuckDB holds strings and offsets its own way. The
ranking is what matters here, not the absolute.
"""

import collections
import glob
import os

import pyarrow.parquet as pq

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"

LEVELS = (
    "workups",
    "inputs.components",
    "outcomes.products",
    "outcomes.products.measurements",
)

# What Parquet spells a repeated hop with. A list contributes ``list.element``; a map
# contributes ``key_value.key`` and ``key_value.value``, and the query grammar names
# none of the four.
_REPEATED = ("list", "key_value")
_WRAPPERS = ("list", "element", "key_value", "value")


def _hops(leaf: str) -> list[str]:
    """Returns the leaf's segments with a marker at each repeated hop.

    Args:
        leaf: A Parquet column path, as ``path_in_schema`` gives it.

    Returns:
        The dotted segments a query would name, with ``*`` standing where the schema
        crossed into a list's elements or a map's values.
    """
    segments: list[str] = []
    for part in leaf.split("."):
        if part in _REPEATED:
            segments.append("*")
        elif part not in _WRAPPERS:
            segments.append(part)
    return segments


def _below(segments: list[str], level: list[str]) -> list[str] | None:
    """Returns the leaf's path below ``level``, or None if it does not sit there.

    The grammar names no wrapper segment, so ``inputs.components`` reaches the
    components under a *map* of inputs and the schema crosses two repeated hops getting
    there. Each level segment therefore consumes an optional hop behind it, and the last
    one has to consume a real one -- a level is repeated by definition.

    Args:
        segments: The leaf's segments, with ``*`` at each repeated hop.
        level: The level's segments, as the query grammar names them.

    Returns:
        The segments from the level's element down to the leaf, or None.
    """
    cursor = 0
    for index, wanted in enumerate(level):
        if cursor >= len(segments) or segments[cursor] != wanted:
            return None
        cursor += 1
        crossed = cursor < len(segments) and segments[cursor] == "*"
        if crossed:
            cursor += 1
        elif index == len(level) - 1:
            return None
    return segments[cursor:]


def main() -> None:
    files = sorted(glob.glob(PROJECTIONS, recursive=True))
    sizes: collections.Counter[str] = collections.Counter()
    total = 0
    for path in files:
        with pq.ParquetFile(path) as projected:
            metadata = projected.metadata
            for group in range(metadata.num_row_groups):
                row_group = metadata.row_group(group)
                for index in range(row_group.num_columns):
                    column = row_group.column(index)
                    sizes[column.path_in_schema] += column.total_uncompressed_size
                    total += column.total_uncompressed_size
    print(f"{len(files)} files, {total / 1024**3:.2f} GiB uncompressed\n")

    marked = [(_hops(leaf), size) for leaf, size in sizes.items()]
    for level in LEVELS:
        kept: dict[str, int] = {}
        dropped = 0
        for segments, size in marked:
            rest = _below(segments, level.split("."))
            if rest is None:
                continue
            # A leaf under a further repeated hop belongs to a deeper level, which
            # _prune removes from this one's element.
            if "*" in rest:
                dropped += size
            else:
                kept[".".join(rest)] = kept.get(".".join(rest), 0) + size
        held = sum(kept.values())
        print(
            f"{level}: {held / 1024**3:.3f} GiB kept across {len(kept)} leaves, "
            f"{dropped / 1024**3:.3f} GiB pruned away"
        )
        by_field: collections.Counter[str] = collections.Counter()
        for leaf, size in kept.items():
            by_field[leaf.split(".")[0]] += size
        for field, size in by_field.most_common(10):
            share = 100 * size / held if held else 0
            print(f"    {field:32s} {size / 1024**3:6.3f} GiB  {share:5.1f}%")
        print()


if __name__ == "__main__":
    main()
