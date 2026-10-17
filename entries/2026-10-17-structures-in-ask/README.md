# Drawn and pasted structures in /ask

- **Date:** 2026-10-17
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; design approved
- **Tags:** ord-schema, ord-app, nl-query, ketcher, structure-search, design
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

The viewer's `/ask` page turns an English question into a search query. A question can
name a compound, and the name is resolved to a structure. It cannot carry a structure
that has no usable name, such as a drawn product, a scaffold, a pattern with an atom
list, or a particular transformation. How should a person put one into a question?

## Summary

The person draws the structure in Ketcher, or pastes SMILES or SMARTS. It becomes a
generated placeholder, `@A`, written in the question and listed under the box. There
are three formats: compound SMILES, compound SMARTS, and reaction SMARTS. The model sees
only each placeholder's name and format. It writes the name where a structure goes, and
the placeholder's text is substituted into the query before validation. As a result:

- the grammar and executor do not change;
- the query that runs names its structures outright;
- a placeholder never reaches a name resolver.

An instructions page with worked examples explains how to ask. The examples double as
evaluation cases.

The design is in [`assets/structures-in-ask-design.md`](assets/structures-in-ask-design.md).

## Method

The design came from a brainstorming session that used mockups of the `/ask` page; the
last one is [`assets/ask-page-mockup.jpg`](assets/ask-page-mockup.jpg). It was checked
against these sources:

- **ord-schema at `cc0be34`:** `ord_schema/search/nl.py`, `query.py`, `execute.py`,
  `nl_log.py`, `nl_eval.py`, and `nl_prompt.md`.
- **ord-app at `7de6638`:**
  - the viewer's `AskPage.tsx` and `routes/ask.py`;
  - the shared `StructureDialog` and `KetcherDialog` in `frontend/packages/ui/src/ketcher/`.

## Conclusions / next steps

1. Write an implementation plan beside the design.
2. Build ord-schema first and release it, then build ord-app.

## References

- [The viewer in ord-app](../2026-10-09-search-and-browse-inside-ord-app/assets/viewer-frontend-design.md),
  whose `/ask` this extends.
- [Reaction SMARTS without the cartridge](../2026-10-02-reaction-smarts-without-the-cartridge/README.md).
- [What a natural-language query should compile to](../2026-07-31-nl-query-over-the-projection/README.md).
