#!/bin/bash
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

# Uploads fixtures to a running ord-app production image in no-auth mode, downloads the
# large dataset in every format while its reactions validate, and samples the
# container's memory throughout.
#
# Usage: check_image.sh <container> <base URL>, from the directory holding uploads/.
set -u
CONTAINER=$1
API=$2/api/v1
AUTH='Authorization: Bearer x'
OUT=image-downloads
mkdir -p "$OUT"
rm -f "$OUT"/* memory.txt
(while docker inspect "$CONTAINER" >/dev/null 2>&1 && [ ! -f "$OUT/stop" ]; do
  docker stats --no-stream --format '{{.MemUsage}}' "$CONTAINER" | cut -d/ -f1 >> memory.txt
done) &
curl -s -o /dev/null -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"access_token": "x", "id_token": "x"}' "$API/auth/jit-provisioning"
GROUP=$(curl -s -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"check"}' \
  "$API/groups" | jq .id)
upload() { curl -s -H "$AUTH" -F "file=@uploads/$1" "$API/groups/$GROUP/datasets/upload" | jq -r .id; }
SMALL=$(upload small.pb)
LARGE=$(upload large.pb.gz)
upload large.parquet >/dev/null
echo "uploaded: small=$SMALL large=$LARGE"
for format in binpb json txtpb parquet; do
  start=$(date +%s)
  status=$(curl -s --compressed -H "$AUTH" -o "$OUT/large.$format" -w '%{http_code}' \
    "$API/datasets/$LARGE/download?file_format=$format")
  echo "large $format: $status, $(( $(wc -c < "$OUT/large.$format") / 1000000 )) MB, $(( $(date +%s) - start )) s"
done
touch "$OUT/stop"
wait
echo "validation batches logged: $(docker logs "$CONTAINER" 2>&1 | grep -c 'bulk update succeeded')"
echo "peak memory: $(sort -h memory.txt | tail -1)," \
  "OOM killed: $(docker inspect "$CONTAINER" --format '{{.State.OOMKilled}}')," \
  "worker deaths: $(docker logs "$CONTAINER" 2>&1 | grep -c 'Child process .* died')"
