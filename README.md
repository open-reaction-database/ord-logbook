# ord-logbook

Logbook for Open Reaction Database analyses, research reports, and notes.

This repo collects investigative work: data analyses, research write-ups, experiment
notes, and anything else worth keeping but not belonging in a code repo. Entries are
living documents — revise and expand them as understanding improves. Keep each entry's
`Status` and `Date` header current so readers know how settled it is, and lean on git
history when you need to see how a conclusion evolved.

## Layout

```text
entries/    one Markdown file per entry, named YYYY-MM-DD-slug.md
assets/     figures, data extracts, and other files referenced by entries
TEMPLATE.md copy this to start a new entry
```

CI lints Markdown and rejects oversized files on every push and pull request
(see `.github/workflows/ci.yml`). Content is licensed under
[CC-BY-SA-4.0](LICENSE), matching `ord-data`.

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
