"""Measure the on-disk cost of a facts-tier derived sidecar.

Derives flat scalar columns from a source Parquet dataset and reports the
sidecar bytes as a fraction of the source bytes. Two column sets are written so
the marginal cost of per-component SMILES is visible separately:

* core: reaction_id, reaction_smiles, yield, conversion, temperature, pressure,
  time, doi, patent, is_negative_result
* full: core plus list<string> columns of input and output component SMILES

Reaction SMILES come from the stored REACTION_SMILES identifier when present;
coverage is reported so a low-coverage dataset is not mistaken for a cheap one.
"""

import argparse
import json
import os
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

from ord_schema import message_helpers, parquet
from ord_schema.logging import silence_rdkit_logs
from ord_schema.proto import reaction_pb2

TEMPERATURE_TO_KELVIN = {
    reaction_pb2.Temperature.CELSIUS: lambda v: v + 273.15,
    reaction_pb2.Temperature.FAHRENHEIT: lambda v: (v - 32.0) * 5.0 / 9.0 + 273.15,
    reaction_pb2.Temperature.KELVIN: lambda v: v,
}
PRESSURE_TO_KPA = {
    reaction_pb2.Pressure.BAR: 100.0,
    reaction_pb2.Pressure.ATMOSPHERE: 101.325,
    reaction_pb2.Pressure.PSI: 6.89476,
    reaction_pb2.Pressure.KPSI: 6894.76,
    reaction_pb2.Pressure.PASCAL: 0.001,
    reaction_pb2.Pressure.KILOPASCAL: 1.0,
    reaction_pb2.Pressure.TORR: 0.133322,
    reaction_pb2.Pressure.MM_HG: 0.133322,
}
TIME_TO_SECONDS = {
    reaction_pb2.Time.HOUR: 3600.0,
    reaction_pb2.Time.MINUTE: 60.0,
    reaction_pb2.Time.SECOND: 1.0,
    reaction_pb2.Time.DAY: 86400.0,
}

CORE_SCHEMA = pa.schema(
    [
        pa.field("reaction_id", pa.string(), nullable=False),
        pa.field("reaction_smiles", pa.string()),
        pa.field("yield_pct", pa.float32()),
        pa.field("conversion_pct", pa.float32()),
        pa.field("temperature_k", pa.float32()),
        pa.field("pressure_kpa", pa.float32()),
        pa.field("time_s", pa.float32()),
        pa.field("doi", pa.string()),
        pa.field("patent", pa.string()),
        pa.field("is_negative_result", pa.bool_()),
    ]
)
FULL_SCHEMA = pa.schema(
    list(CORE_SCHEMA)
    + [
        pa.field("input_smiles", pa.list_(pa.string())),
        pa.field("output_smiles", pa.list_(pa.string())),
    ]
)


def _reaction_smiles(reaction: reaction_pb2.Reaction) -> str | None:
    for identifier in reaction.identifiers:
        if identifier.type == reaction_pb2.ReactionIdentifier.REACTION_SMILES:
            return identifier.value or None
    return None


def _compound_smiles(compound) -> str | None:
    for identifier in compound.identifiers:
        if identifier.type == reaction_pb2.CompoundIdentifier.SMILES:
            return identifier.value or None
    return None


def _temperature_k(reaction: reaction_pb2.Reaction) -> float | None:
    setpoint = reaction.conditions.temperature.setpoint
    if not setpoint.HasField("value"):
        return None
    convert = TEMPERATURE_TO_KELVIN.get(setpoint.units)
    return convert(setpoint.value) if convert else None


def _pressure_kpa(reaction: reaction_pb2.Reaction) -> float | None:
    setpoint = reaction.conditions.pressure.setpoint
    if not setpoint.HasField("value"):
        return None
    factor = PRESSURE_TO_KPA.get(setpoint.units)
    return setpoint.value * factor if factor else None


def _outcome_scalars(reaction: reaction_pb2.Reaction):
    """Returns (yield_pct, conversion_pct, time_s) from the first outcome."""
    if not reaction.outcomes:
        return None, None, None
    outcome = reaction.outcomes[0]
    conversion = outcome.conversion.value if outcome.conversion.HasField("value") else None
    time_s = None
    if outcome.reaction_time.HasField("value"):
        factor = TIME_TO_SECONDS.get(outcome.reaction_time.units)
        if factor:
            time_s = outcome.reaction_time.value * factor
    best_yield = None
    for product in outcome.products:
        for measurement in product.measurements:
            if measurement.type != reaction_pb2.ProductMeasurement.YIELD:
                continue
            if not measurement.HasField("percentage"):
                continue
            if not measurement.percentage.HasField("value"):
                continue
            value = measurement.percentage.value
            if best_yield is None or value > best_yield:
                best_yield = value
    return best_yield, conversion, time_s


def _component_smiles(reaction: reaction_pb2.Reaction):
    inputs = []
    for reaction_input in reaction.inputs.values():
        for compound in reaction_input.components:
            smiles = _compound_smiles(compound)
            if smiles:
                inputs.append(smiles)
    outputs = []
    for outcome in reaction.outcomes:
        for product in outcome.products:
            smiles = _compound_smiles(product)
            if smiles:
                outputs.append(smiles)
    return inputs, outputs


def derive(
    source: str,
    out_core: str,
    out_full: str,
    max_row_groups: int | None,
    generate: bool,
):
    silence_rdkit_logs()
    footer = parquet.load_footer(source)
    total_row_groups = footer.num_row_groups
    if max_row_groups is None or max_row_groups >= total_row_groups:
        groups = list(range(total_row_groups))
    else:
        # Evenly spaced across the file: USPTO row groups are written in source
        # order, so a leading prefix would not represent the whole dataset.
        stride = total_row_groups / max_row_groups
        groups = sorted({int(i * stride) for i in range(max_row_groups)})
    core_writer = pq.ParquetWriter(out_core, CORE_SCHEMA, compression="zstd")
    full_writer = pq.ParquetWriter(out_full, FULL_SCHEMA, compression="zstd")
    rows = 0
    with_smiles = 0
    generated = 0
    start = time.time()
    try:
        for row_group in groups:
            batch = {name: [] for name in FULL_SCHEMA.names}
            for reaction_id, reaction in parquet.iter_reactions(source, row_group=row_group):
                smiles = _reaction_smiles(reaction)
                if smiles:
                    with_smiles += 1
                elif generate:
                    try:
                        smiles = message_helpers.get_reaction_smiles(
                            reaction, generate_if_missing=True
                        )
                    except Exception:  # noqa: BLE001 - measurement, not production
                        smiles = None
                    if smiles:
                        generated += 1
                yield_pct, conversion_pct, time_s = _outcome_scalars(reaction)
                inputs, outputs = _component_smiles(reaction)
                batch["reaction_id"].append(reaction_id)
                batch["reaction_smiles"].append(smiles)
                batch["yield_pct"].append(yield_pct)
                batch["conversion_pct"].append(conversion_pct)
                batch["temperature_k"].append(_temperature_k(reaction))
                batch["pressure_kpa"].append(_pressure_kpa(reaction))
                batch["time_s"].append(time_s)
                batch["doi"].append(reaction.provenance.doi or None)
                batch["patent"].append(reaction.provenance.patent or None)
                batch["is_negative_result"].append(
                    None if yield_pct is None else yield_pct == 0.0
                )
                batch["input_smiles"].append(inputs)
                batch["output_smiles"].append(outputs)
                rows += 1
            full_table = pa.Table.from_pydict(batch, schema=FULL_SCHEMA)
            full_writer.write_table(full_table)
            core_writer.write_table(full_table.select(CORE_SCHEMA.names).cast(CORE_SCHEMA))
    finally:
        core_writer.close()
        full_writer.close()
    return {
        "source": source,
        "source_bytes": os.path.getsize(source),
        "source_rows": footer.num_rows,
        "source_row_groups": total_row_groups,
        "sampled_row_groups": len(groups),
        "rows": rows,
        "smiles_stored": round(with_smiles / rows, 4) if rows else 0.0,
        "smiles_generated": round(generated / rows, 4) if rows else 0.0,
        "core_bytes": os.path.getsize(out_core),
        "full_bytes": os.path.getsize(out_full),
        "seconds": round(time.time() - start, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-row-groups", type=int, default=None)
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a reaction SMILES when none is stored (RDKit).",
    )
    args = parser.parse_args()
    stem = os.path.basename(args.source).removesuffix(".parquet")
    result = derive(
        args.source,
        os.path.join(args.out_dir, f"{stem}.core.parquet"),
        os.path.join(args.out_dir, f"{stem}.full.parquet"),
        args.max_row_groups,
        args.generate,
    )
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
