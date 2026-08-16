"""Is a flat element index fast enough to replace the nested narrow tables?

Size is settled: 2.68 GB flat against 12.05 GB nested. This asks the other half -- what
the mixed benchmark costs when its quantifiers become semi-joins against flat tables
rather than list comprehensions over decoded structs. Builds once into a database file,
then times each query with the tables loaded into memory.
"""

import os
import pathlib
import time

import duckdb

HOME = os.path.expanduser("~")
GLOB = f"{HOME}/ord/projections/**/*.parquet"
FLAT = pathlib.Path("/tmp/ord_flat.duckdb")  # noqa: S108 - a scratch measurement.

BUILD = {
    # Reaction-level scalars: one row per reaction, no quantifier needed to reach them.
    "reaction": f"""
        SELECT reaction_id,
               conditions.temperature.setpoint_kelvin AS temperature_kelvin,
               conditions.pressure.setpoint_kilopascals AS pressure_kilopascals,
               notes.procedure_details AS procedure_details
        FROM read_parquet('{GLOB}')
    """,
    "measurement": f"""
        SELECT reaction_id,
               outcome_index::UINTEGER AS outcome_index,
               product_index::UINTEGER AS product_index,
               measurement.type AS type,
               measurement.percentage.value AS percentage_value
        FROM read_parquet('{GLOB}'),
             unnest(outcomes) WITH ORDINALITY AS o(outcome, outcome_index),
             unnest(outcome.products) WITH ORDINALITY AS p(product, product_index),
             unnest(product.measurements) AS m(measurement)
    """,
    "product": f"""
        SELECT reaction_id,
               outcome_index::UINTEGER AS outcome_index,
               product.isolated_color AS isolated_color,
               product.is_desired_product AS is_desired_product,
               product.structure_id AS structure_id
        FROM read_parquet('{GLOB}'),
             unnest(outcomes) WITH ORDINALITY AS o(outcome, outcome_index),
             unnest(outcome.products) AS p(product)
    """,
}

# The mixed benchmark's projection-only clauses, as semi-joins against the flat tables.
QUERIES = {
    "yield > 50%": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT reaction_id FROM measurement
            WHERE type = 'YIELD' AND percentage_value > 50
        )
    """,
    "a white product": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT reaction_id FROM product WHERE isolated_color = 'white'
        )
    """,
    "above 350 K": """
        SELECT count(*) FROM reaction WHERE temperature_kelvin > 350
    """,
    # Correlated within one element: the yield and its normalization must be the same
    # measurement, which is what element identity in a flat row preserves.
    "desired product, yield > 50%": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT m.reaction_id FROM measurement AS m
            JOIN product AS p
              ON p.reaction_id = m.reaction_id
             AND p.outcome_index = m.outcome_index
            WHERE m.type = 'YIELD' AND m.percentage_value > 50
              AND p.is_desired_product
        )
    """,
}


def _build() -> None:
    if FLAT.exists():
        print(f"reusing {FLAT} ({FLAT.stat().st_size / 1024**3:.2f} GB)", flush=True)
        return
    connection = duckdb.connect(str(FLAT))
    try:
        connection.execute("SET preserve_insertion_order=false")
        connection.execute("SET memory_limit='10GB'")
        for name, select in BUILD.items():
            start = time.perf_counter()
            connection.execute(f"CREATE TABLE {name} AS {select}")
            rows = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            print(
                f"  built {name:14s} {rows:12,d} rows in "
                f"{time.perf_counter() - start:5.0f}s",
                flush=True,
            )
    finally:
        connection.close()
    print(f"wrote {FLAT.stat().st_size / 1024**3:.2f} GB", flush=True)


def _held(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "SELECT sum(memory_usage_bytes) FROM duckdb_memory() "
        "WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()
    return int(row[0] or 0)


def main() -> None:
    _build()
    connection = duckdb.connect()
    connection.execute("SET memory_limit='8GB'")
    connection.execute(f"ATTACH '{FLAT}' AS flat (READ_ONLY)")
    start = time.perf_counter()
    for name in BUILD:
        connection.execute(f"CREATE TABLE {name} AS SELECT * FROM flat.{name}")
    print(
        f"\nloaded into memory: {_held(connection) / 1024**3:.2f} GB "
        f"in {time.perf_counter() - start:.0f}s\n",
        flush=True,
    )
    for label, sql in QUERIES.items():
        best = None
        for _ in range(3):
            start = time.perf_counter()
            count = connection.execute(sql).fetchone()[0]
            spent = time.perf_counter() - start
            best = spent if best is None else min(best, spent)
        print(f"  {label:30s} {best:6.3f}s  ({count:,} reactions)", flush=True)
    connection.close()


if __name__ == "__main__":
    main()
