# Checks after the ord-app redeploy

- **Date:** 2026-10-04
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

These checks need a signed-in account and prod's own data, so they run on
<https://app.open-reaction-database.org> right after the redeploy. Everything that
could be checked without an account passed locally ([the entry](../README.md), §4 and
§5). For anything that fails, note the page, the account, and a screenshot or the
error from the browser's console.

## 1. Sign-in

- [ ] Sign in: Auth0's page opens, and you land back in the app signed in.
- [ ] In the browser's network tab, API requests go to
  `https://app.open-reaction-database.org/api/v1/...`.

## 2. Existing datasets and reactions

ord-schema went from 0.3 to 0.6, and reactions are stored as serialized protos.

- [ ] Open a few existing datasets, including a large one, and page through their
  reactions.
- [ ] Open a reaction, edit a field, save, and reload: the edit is kept.
- [ ] Validation results look as they did before the redeploy.

## 3. Downloads

- [ ] From a dataset's page, download it as `.binpb`, `.txtpb`, `.json`, and
  `.parquet`. Each appears in the browser's own downloads list with its progress, and
  the page stays where it is.
- [ ] Do the same from the menu in the datasets list.
- [ ] Download a single reaction from its page.
- [ ] A dataset or reaction with `µ`, `°`, or an en dash in its name or text downloads
  in every format, under its exact name.

## 4. Structures (Ketcher 3.8 to 3.15)

- [ ] Draw a structure and save it to a component.
- [ ] Add a SMILES and a molblock identifier; each shows the right structure.
- [ ] Copy a reaction's image.

## 5. Access and roles, with a second account

- [ ] A dataset the second account cannot access shows as not found.
- [ ] As a viewer, the second account cannot edit.
- [ ] Only a group admin can remove a dataset.
- [ ] Attachments over 10 MB in total on one reaction are refused.
- [ ] Remove the second account's access while it has a dataset open: its next edit
  is refused, the edit rolls back, and it is told why.
