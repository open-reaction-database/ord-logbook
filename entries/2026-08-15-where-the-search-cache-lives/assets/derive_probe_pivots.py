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

"""Derives pivot artifacts over the local corpus, for measurement only.

The local projections were written by an older ord_schema than the one installed, so
they read as stale and ``write_pivot`` refuses them -- correctly, since an artifact
derived from a stale parent would claim a provenance it does not have. Nothing here
ships, and the corpus these are measured against is opened with
``require_current=False``, so the check is stubbed out rather than the projections
rebuilt.
"""

import os
import pathlib
import time

from ord_schema.artifacts import base
from ord_schema.artifacts.scripts import derive_pivots

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/*/*.parquet"
OUTPUT = f"{HOME}/ord/pivots"

LEVELS = (
    "workups",
    "outcomes.products",
    "outcomes.products.measurements",
    "inputs.components",
)


def _stamped_by_this_library(stamps, artifact: str) -> bool:
    """Accepts any artifact of the right kind, whatever version wrote it."""
    return stamps.artifact == artifact


def main() -> None:
    # Both the driver and the writer reach this through the module, so one patch covers
    # the parent check and the skip-if-current check alike.
    base.stamps_are_current = _stamped_by_this_library
    for level in LEVELS:
        start = time.perf_counter()
        derive_pivots.main(
            derive_pivots.parse_args(
                [
                    f"--input_pattern={PROJECTIONS}",
                    f"--output_dir={OUTPUT}",
                    "--levels",
                    level,
                ]
            )
        )
        held = sum(
            path.stat().st_size
            for path in pathlib.Path(OUTPUT, level).rglob("*.parquet")
        )
        print(
            f"{level}: {held / 1024**3:.3f} GiB on disk in "
            f"{time.perf_counter() - start:.0f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
