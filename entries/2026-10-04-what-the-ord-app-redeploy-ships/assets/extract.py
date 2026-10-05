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

"""Write a sample of ord-data reactions as serialized Reaction protos, one file per dataset."""

import itertools
import pathlib
import random
import sys

from ord_schema import parquet

DATA = pathlib.Path(sys.argv[1])  # ord-data's data/ directory
OUT = pathlib.Path("corpus")
OUT.mkdir(exist_ok=True)
files = sorted(DATA.glob("*/*.parquet"))
random.seed(0)
total = 0
for path in files:
    reactions = list(itertools.islice(parquet.iter_reactions(path), 300))
    with open(OUT / f"{path.stem}.bin", "wb") as handle:
        for reaction in reactions:
            if isinstance(reaction, tuple):
                reaction = next(item for item in reaction if hasattr(item, "SerializeToString"))
            data = reaction.SerializeToString()
            handle.write(len(data).to_bytes(4, "big") + data)
    total += len(reactions)
print(f"{len(files)} datasets, {total} reactions")
