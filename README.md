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
(see `.github/workflows/ci.yml`). The same checks run locally via
[pre-commit](https://pre-commit.com) — install once with:

```bash
pre-commit install
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

## License

This repository carries two licenses, because it holds both writing and code:

| what | license | file |
| --- | --- | --- |
| The entries under `entries/`, and the figures and data extracts under `assets/` | [CC-BY-SA-4.0](LICENSE) | `LICENSE` |
| The scripts under `assets/` and the workflows under `.github/` | [Apache-2.0](LICENSE-CODE) | `LICENSE-CODE` |

CC-BY-SA-4.0 matches [ord-data](https://github.com/Open-Reaction-Database/ord-data),
so a figure or table can move between the two repositories without a license change.

The code carries a separate license because Creative Commons licenses are not
intended for software — [Creative Commons recommends against
it](https://creativecommons.org/faq/#can-i-apply-a-creative-commons-license-to-software)
— and because the project's other code repositories, including
[ord-schema](https://github.com/Open-Reaction-Database/ord-schema), are
Apache-2.0. The analysis scripts here are meant to be reusable, so they get the
license people expect to find on code.
