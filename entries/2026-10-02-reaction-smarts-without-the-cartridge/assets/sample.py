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

"""Draws the reaction sample the comparisons read, from a built projection tree.

20,000 reactions from the USPTO dataset (``ord_dataset-1158e351...``) and 20,000 from the
rest of the corpus, each a reservoir sample with seed 7, with each reaction's SMILES, its
input components, and its products.

Usage: python sample.py PROJECTIONS_DIR OUT.parquet
"""

import glob
import sys

import duckdb

_SELECT = """
SELECT reaction_id, smiles AS rxn_smiles,
  flatten(list_transform(map_values(inputs),
    x -> list_transform(x.components, c -> {'smiles': c.smiles, 'role': c.reaction_role})))
    AS inputs,
  flatten(list_transform(outcomes,
    o -> list_transform(o.products, p -> {'smiles': p.smiles, 'role': p.reaction_role})))
    AS products
FROM read_parquet(FILES)
"""


def main() -> None:
    root, out = sys.argv[1], sys.argv[2]
    files = sorted(glob.glob(f"{root}/*/*.parquet"))
    uspto = [f for f in files if "1158e351" in f]
    others = [f for f in files if "1158e351" not in f]
    listed = lambda fs: "[" + ", ".join(f"'{f}'" for f in fs) + "]"
    connection = duckdb.connect()
    for table, chosen in (("u", uspto), ("o", others)):
        connection.execute(
            f"CREATE TABLE {table} AS "
            + _SELECT.replace("FILES", listed(chosen))
            + " USING SAMPLE 20000 ROWS (reservoir, 7)"
        )
    connection.execute(
        "COPY (SELECT 'uspto' AS source, * FROM u UNION ALL SELECT 'other' AS source, * "
        f"FROM o) TO '{out}'"
    )


if __name__ == "__main__":
    main()
