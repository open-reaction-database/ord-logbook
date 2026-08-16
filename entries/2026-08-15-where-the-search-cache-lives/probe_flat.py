"""How big is a flat element index, versus the decoded nested column it replaces?

The narrow tables are expensive because they hold decoded *nested* data. A flat table
holding one row per element of a repeated path, with only the scalar leaves, is the same
information for predicate purposes and is a shape any row store can hold. This measures
its rows and its resident bytes.
"""

import os
import time

import duckdb

HOME = os.path.expanduser("~")
GLOB = f"{HOME}/ord/projections/**/*.parquet"

# One entry per repeated path the mixed benchmark touches: the flattening SQL, and the
# scalar leaves a predicate over that path could ask about.
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


def _held(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "SELECT sum(memory_usage_bytes) FROM duckdb_memory() "
        "WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()
    return int(row[0] or 0)


def main() -> None:
    connection = duckdb.connect()
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(
        f"CREATE VIEW reactions AS SELECT * FROM read_parquet('{GLOB}')"
    )
    total = 0
    for path, select in FLAT.items():
        before = _held(connection)
        start = time.perf_counter()
        name = path.replace(".", "_")
        connection.execute(f"CREATE TABLE {name} AS {select}")
        spent = time.perf_counter() - start
        held = _held(connection) - before
        rows = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        total += held
        print(
            f"{path:36s} {rows:12,d} rows  {held / 1024**3:6.2f} GB  built {spent:5.1f}s",
            flush=True,
        )
    print(f"{'TOTAL':36s} {'':12s}       {total / 1024**3:6.2f} GB")


if __name__ == "__main__":
    main()
