"""Nested-leaf access across readers (finding 4).

The projection's performance argument is that Parquet prunes to struct leaves. That is
true of the file; it is not true of every reader.
"""
import time
import warnings

import pandas as pd
import polars as pl
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

PROJECTION = "/path/to/norm_out/ord_dataset-....parquet"
LEAF = "conditions.temperature.setpoint.value_kelvin"

start = time.time()
frame = pd.read_parquet(PROJECTION, columns=["conditions"])
print(f"pandas, whole conditions struct: {time.time() - start:.2f}s, dtype={frame['conditions'].dtype}")
print(f"  one cell is a {type(frame['conditions'].iloc[0]).__name__}; leaves need per-row traversal")
try:
    pd.read_parquet(PROJECTION, columns=[LEAF])
    print("  dotted leaf selection: supported")
except Exception as error:  # noqa: BLE001 - reporting which readers refuse
    print(f"  dotted leaf selection: NOT supported ({type(error).__name__})")

print(f"polars, conditions dtype: {str(pl.scan_parquet(PROJECTION).collect_schema()['conditions'])[:70]}")
print(f"pyarrow schema field: {pq.ParquetFile(PROJECTION).schema_arrow.field('conditions').type}"[:120])
