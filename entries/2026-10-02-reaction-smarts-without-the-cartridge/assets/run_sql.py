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

"""Runs SQL from stdin against a throwaway Postgres with the RDKit cartridge.

Needs initdb and an RDKit-enabled Postgres on PATH (the conda ``rdkit-postgresql``
build), and the testing.postgresql and psycopg packages.
"""

import sys

import psycopg
import testing.postgresql


def main() -> None:
    with testing.postgresql.Postgresql() as pg, psycopg.connect(pg.url(), autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS rdkit")
        for statement in sys.stdin.read().split(";\n"):
            statement = "\n".join(
                line for line in statement.splitlines() if not line.startswith("--")
            ).strip()
            if not statement:
                continue
            cursor = conn.execute(statement)
            if cursor.description is None:
                continue
            for row in cursor.fetchall():
                print(" | ".join(str(value) for value in row))


if __name__ == "__main__":
    main()
