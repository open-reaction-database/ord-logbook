# ord-logbook

Logbook for Open Reaction Database analyses, research reports, and notes.

This repo is a chronological record of investigative work: data analyses, research
write-ups, experiment notes, and anything else worth keeping but not belonging in a
code repo. Think of it as a lab notebook — entries are append-only history, not living
documentation. Don't rewrite old entries; add a new one and link back.

## Layout

```
entries/    one Markdown file per entry, named YYYY-MM-DD-slug.md
assets/     figures, data extracts, and other files referenced by entries
TEMPLATE.md copy this to start a new entry
```

## Adding an entry

```bash
cp TEMPLATE.md entries/$(date +%Y-%m-%d)-short-slug.md
# write it up, drop any figures in assets/
git add entries assets
git commit -m "Add entry: short description"
git push
```

Keep figures and large outputs under `assets/<entry-slug>/` so each entry's files
are easy to find. For anything large or binary-heavy, link out rather than committing
it here.

## Index

Newest first.

| Date | Entry | Summary |
|------|-------|---------|
| _—_  | _first entry goes here_ | |
