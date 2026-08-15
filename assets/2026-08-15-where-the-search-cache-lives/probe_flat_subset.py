"""Bytes per element of a flat index, measured on a row sample and scaled to the corpus.

Sampling by row rather than by directory: one directory holds 88% of this corpus, so a
directory subset is not a sample of it. The sample must also be large enough that
DuckDB's block granularity is negligible against the data, which a few thousand rows is
not.
"""

import os
import time

import duckdb

HOME = os.path.expanduser("~")
GLOB = f"'{HOME}/ord/projections/**/*.parquet'"
SAMPLE = 200_000

FLAT = {
    "outcomes.products.measurements": """
        SELECT reaction_id,
               outcome_index::UINTEGER AS outcome_index,
               product_index::UINTEGER AS product_index,
               measurement.type AS type,
               measurement.percentage.value AS percentage_value,
               measurement.float_value.value AS float_value,
               measurement.retention_time_seconds AS retention_time_seconds,
               measurement.is_normalized AS is_normalized,
               measurement.uses_internal_standard AS uses_internal_standard
        FROM reactions,
             unnest(outcomes) WITH ORDINALITY AS o(outcome, outcome_index),
             unnest(outcome.products) WITH ORDINALITY AS p(product, product_index),
             unnest(product.measurements) AS m(measurement)
    """,
    "outcomes.products": """
        SELECT reaction_id,
               outcome_index::UINTEGER AS outcome_index,
               product.isolated_color AS isolated_color,
               product.is_desired_product AS is_desired_product,
               product.texture.type AS texture_type,
               product.structure_id AS structure_id
        FROM reactions,
             unnest(outcomes) WITH ORDINALITY AS o(outcome, outcome_index),
             unnest(outcome.products) AS p(product)
    """,
    "inputs.components": """
        SELECT reaction_id,
               entry.key AS input_key,
               component.reaction_role AS reaction_role,
               component.is_limiting AS is_limiting,
               component.amount.mass_grams AS mass_grams,
               component.amount.moles_moles AS moles_moles,
               component.amount.volume_liters AS volume_liters,
               component.structure_id AS structure_id
        FROM reactions,
             unnest(map_entries(inputs)) AS i(entry),
             unnest(entry.value.components) AS c(component)
    """,
    "workups": """
        SELECT reaction_id,
               workup.type AS type,
               workup.duration_seconds AS duration_seconds,
               workup.temperature.setpoint_kelvin AS setpoint_kelvin,
               workup.is_automated AS is_automated
        FROM reactions, unnest(workups) AS w(workup)
    """,
}

CORPUS_REACTIONS = 2_428_291


def _held(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "SELECT sum(memory_usage_bytes) FROM duckdb_memory() "
        "WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()
    return int(row[0] or 0)


def main() -> None:
    connection = duckdb.connect()
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET memory_limit='6GB'")
    connection.execute("SET threads=4")
    connection.execute(
        f"CREATE TABLE reactions AS SELECT * FROM read_parquet({GLOB}) LIMIT {SAMPLE}"
    )
    sampled = connection.execute("SELECT count(*) FROM reactions").fetchone()[0]
    scale = CORPUS_REACTIONS / sampled
    print(f"{sampled:,} reactions sampled, scale x{scale:.1f}\n", flush=True)
    total = 0
    for path, select in FLAT.items():
        name = path.replace(".", "_")
        before = _held(connection)
        start = time.perf_counter()
        connection.execute(f"CREATE TABLE {name} AS {select}")
        spent = time.perf_counter() - start
        held = _held(connection) - before
        rows = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        projected = held * scale
        total += projected
        print(
            f"{path:34s} {rows:11,d} rows  {held / 1024**2:7.1f} MB "
            f" corpus {projected / 1024**3:5.2f} GB  ({spent:5.1f}s)",
            flush=True,
        )
    print(f"\n{'CORPUS TOTAL':34s} {total / 1024**3:5.2f} GB")
    print("versus 12.05 GB for the same three top-level columns held nested")


if __name__ == "__main__":
    main()
