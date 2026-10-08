# Scripts for the ord-app redeploy checks

- **Date:** 2026-10-04
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Each script pins nothing itself; run it with the ord-schema version under test, for
example `uv run --no-project --python 3.12 --with 'ord-schema==0.3.100' --with
'protobuf<5' python <script>` for prod's version and `--with 'ord-schema==0.6.31'` for
`main`'s. Run them from one working directory; they share `corpus/`, `uploads/`, and
`downloads/` there.

| script | what it does |
| --- | --- |
| `dump_descriptors.py` | Prints every field (number, type, label, target) and enum value reachable from `Reaction` and `Dataset`, as JSON, for diffing two versions. |
| `extract.py <ord-data/data>` | Writes up to 300 reactions from each ord-data Parquet file to `corpus/`, length-prefixed. Needs ord-schema ≥ 0.6. |
| `validate.py <out.json>` | Validates the corpus as ord-app does (`require_provenance=True`) and writes each reaction's errors and warnings. |
| `rules.py` | Validates a minimal reaction under targeted mutations, one per rule ord-schema #817 added, and prints the errors and warnings for each. |
| `prep_uploads.py <ord-data/data>` | Picks a small, a medium, and a large ord-data dataset and writes each as `.pb`, `.pb.gz`, `.pbtxt`, `.json`, and `.parquet` into `uploads/`. |
| `exercise_api.py <labels> <suffixes>` | Against an ord-app backend in no-auth mode on `127.0.0.1:8000`: uploads each fixture, pages through it, and downloads it in every format into `downloads/`. Run with ord-app's own environment (`uv run --project <ord-app>`). |
| `roundtrip.py` | Compares each downloaded dataset with the uploaded original, reaction by reaction. |
| `serialize_mem.py <binpb\|json\|txtpb>` | Peak memory of parsing `uploads/large.pb` and serializing it one way. |
| `check_image.sh <container> <base URL>` | Against a running production image in no-auth mode: uploads the small and large fixtures, downloads the large dataset in every format while its reactions validate, and reports each response, the peak of the container's memory, OOM kills, and worker deaths. Start the image with `docker run --platform linux/amd64 --cpus 2 --memory 4g -e APP_ENV=localhost -e ORD_APP_E2E=true -e PG_DSN=... -p 8089:5173 <image>`. Needs `jq`. |

`redeploy-checklist.md` is the list of signed-in checks to run on prod after the redeploy.
