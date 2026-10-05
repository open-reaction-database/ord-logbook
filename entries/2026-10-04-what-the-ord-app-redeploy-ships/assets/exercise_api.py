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

"""Upload each fixture through the dev API, page through it, and download it in every format."""

import json
import pathlib
import subprocess
import sys
import time

import httpx

API = "http://127.0.0.1:8000/service_api/api/v1"
client = httpx.Client(base_url=API, headers={"Authorization": "Bearer e2e-dev-token"}, timeout=1800)
manifest = json.load(open("uploads/manifest.json"))
labels = sys.argv[1].split(",")
suffixes = sys.argv[2].split(",")


def backend_rss_mb():
    out = subprocess.run(["pgrep", "-f", "uvicorn ord_app.service_api.main:app"], capture_output=True, text=True).stdout.split()
    return sum(int(subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True).stdout.strip() or 0) for pid in out) // 1024


me = client.get("/users/me").raise_for_status().json()
group = client.post("/groups", json={"name": f"verify-{int(time.time())}"}).raise_for_status().json()
gid = group["id"]
results = []
for label in labels:
    expected = manifest[label]["reactions"]
    for suffix in suffixes:
        path = pathlib.Path(f"uploads/{label}{suffix}")
        start = time.time()
        response = client.post(f"/groups/{gid}/datasets/upload", files={"file": (path.name, path.read_bytes())})
        row = {"fixture": path.name, "upload_status": response.status_code, "upload_s": round(time.time() - start, 1), "rss_mb": backend_rss_mb()}
        if response.status_code >= 300:
            row["error"] = response.text[:300]
            results.append(row)
            print(json.dumps(row), flush=True)
            continue
        dataset_id = response.json()["id"]
        row["dataset_id"] = dataset_id
        page = client.get(f"/datasets/{dataset_id}/reactions", params={"page": 1, "size": 50})
        body = page.json()
        row["list_status"] = page.status_code
        row["total"] = body.get("total")
        row["matches"] = body.get("total") == expected
        row["pages"] = body.get("pages")
        last = client.get(f"/datasets/{dataset_id}/reactions", params={"page": body.get("pages") or 1, "size": 50})
        row["last_page_items"] = len(last.json().get("items", []))
        for fmt in ("binpb", "json", "txtpb", "parquet"):
            start = time.time()
            try:
                download = client.get(f"/datasets/{dataset_id}/download", params={"file_format": fmt})
            except httpx.HTTPError as error:
                row[f"dl_{fmt}"] = f"ERROR {type(error).__name__}"
                continue
            out = pathlib.Path(f"downloads/{label}-{suffix.strip('.').replace('.', '_')}.{fmt}")
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(download.content)
            row[f"dl_{fmt}"] = f"{download.status_code} {len(download.content) // 1024}KB {round(time.time() - start, 1)}s"
        row["rss_mb_after"] = backend_rss_mb()
        results.append(row)
        print(json.dumps(row), flush=True)
json.dump(results, open(f"exercise-{'_'.join(labels)}.json", "w"), indent=1)
