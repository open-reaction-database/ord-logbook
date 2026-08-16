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

"""Count distinct component SMILES across the derived views."""
import glob, json
import pyarrow.parquet as pq
import pyarrow.compute as pc

seen = set()
rows = 0
for f in sorted(glob.glob("/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/views_out2/*.parquet")):
    t = pq.read_table(f, columns=["input_smiles", "output_smiles"])
    rows += t.num_rows
    for col in ("input_smiles", "output_smiles"):
        flat = pc.list_flatten(t[col].combine_chunks())
        seen.update(flat.to_pylist())
seen.discard(None)
print(json.dumps({"rows": rows, "distinct_component_smiles": len(seen)}))
with open("/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/uniq_smiles.txt", "w") as f:
    for s in seen:
        f.write(s + "\n")
