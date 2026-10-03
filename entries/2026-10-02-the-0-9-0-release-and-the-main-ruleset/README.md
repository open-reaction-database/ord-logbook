# Why the 0.9.0 release published but could not push to main

- **Date:** 2026-10-02
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** final; the fix is untested until the next release
- **Tags:** ord-schema, release, ci, github, rulesets, bsr, incident
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

The ord-schema 0.9.0 release
([run 37083600036](https://github.com/open-reaction-database/ord-schema/actions/runs/37083600036))
published to PyPI and npm and then failed. What failed, what state did it leave each
destination in, how was it repaired, and what is different now?

## Summary

**`publish.yml` pushes its version bump straight to `main`, and the `main` ruleset had
stopped allowing that.** The ruleset was last changed on 2026-08-08, four days after the
previous release succeeded. It requires a pull request and 11 status checks, and every
actor on its bypass list — org admins, the maintain role, the admin role — has bypass
mode `pull_request`, which applies when merging a pull request and never to a direct
push. The workflow pushes as `ord-service`, which holds the maintain role, so the first
release after the change could not land its bump.

The workflow publishes before it pushes, so the failure came after the irreversible
steps. PyPI, npm, and the BSR all have 0.9.0, the `v0.9.0` tag was pushed, and only the
bump on `main` and the GitHub release were missing. Both were filled in by hand:
[ord-schema#1088](https://github.com/open-reaction-database/ord-schema/pull/1088) for
the bump, `gh release create` for the release. `ord-service` now has bypass mode
`always` on both rulesets that cover `main`.

**Nothing was lost and nothing needs rewriting.** The one lasting oddity is that the
`v0.9.0` tag points at a commit that is not in `main`'s history but has the identical
tree, and a branch, `release/v0.9.0`, keeps GitHub's web pages for it working.

## Method

- The run's logs (`gh run view 37083600036 --log`), for the timeline and the rejection.
- The rulesets, from `gh api repos/open-reaction-database/ord-schema/rulesets`, and
  `rules/branches/main` for every rule in effect on `main`.
- The repository activity API, which names the account behind each direct push to
  `main`: `ord-service` made the 0.8.1, 0.8.2, and 0.8.3 release pushes on 2026-08-03
  and 2026-08-04.
- PyPI's JSON API, the npm registry, and `buf registry module label info` /
  `buf export` for what each destination held afterward.
- Anonymous requests to GitHub's web pages for the tagged commit, before and after a
  branch pointed at it.

## Findings

### 1. What happened, in order

All times UTC, on 2026-10-03 (the evening of 2026-10-02 in US Eastern).

| time | step | result |
| --- | --- | --- |
| 00:48:34 | `publish.yml` dispatched at `main` = `61c5443`, level `minor` | |
| 00:49:01 | `bump-my-version` commits `8e37a82` and creates the annotated tag `v0.9.0` (tag object `c202c22`) | |
| 00:49:09 | wheel and sdist uploaded to PyPI | published |
| 00:49:26 | `npm publish` of `ord-schema@0.9.0` | published |
| 00:49:38 | `npm publish` of `ord-schema-protobufjs@0.9.0` | published |
| 00:49:40 | `git push origin main --tags` | tag accepted; `main` rejected (`GH013`) |
| — | `gh release create` | skipped |
| 00:49:59 | `push_proto` pushes the newest `v*` tag to the BSR | BSR commit `2a4e5a8d…`, labels `v0.9.0` and `latest` |

The rejection, verbatim:

```text
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Changes must be made through a pull request.
remote: - 11 of 11 required status checks are expected.
 * [new tag]         v0.9.0 -> v0.9.0
 ! [remote rejected] main -> main (push declined due to repository rule violations)
```

`push_proto` runs when `publish` fails and pushes the newest tag rather than the
workflow's own commit, a design made so a release that fails after its tag push still
reaches the BSR
([the buf migration entry](../2026-08-26-migrating-the-proto-build-to-buf/README.md),
stage 2 step 3). This was the case it was built for, and it worked.

npm accepted both packages at once but listed neither for several minutes; the
registry's `latest` dist-tag read 0.8.3 until then.

### 2. Why the push was refused

Two repository rulesets apply to `main`:

| ruleset | id | rules | bypass actors before the fix |
| --- | --- | --- | --- |
| `main` | 16006752 | deletion, non-fast-forward, linear history, pull request, required status checks | org admins, maintain role, admin role — all `pull_request` |
| `approval` | 17932699 | pull request | the same three, `pull_request`; one maintainer's account, `exempt` |

A ruleset bypass has three modes. `always` lets the actor through on any push;
`pull_request` only when the change arrives by merging a pull request; `exempt` skips
the rules entirely and writes no bypass audit entry. A direct push from the workflow is
not a pull request, so `pull_request` mode for the maintain role was no bypass at all.

The account is `ord-service`, a machine user with the maintain role. `publish.yml` checks
out with the org-level secret `ACTIONS_PUSH`, which cannot be read from the repository;
the activity API is what ties it to `ord-service`, which made the previous three release
pushes to `main`.

### 3. What each destination held afterward

| destination | state |
| --- | --- |
| PyPI | 0.9.0, wheel and sdist |
| npm | `ord-schema` and `ord-schema-protobufjs` 0.9.0, each `latest` |
| BSR | `v0.9.0` on commit `2a4e5a8d…`; `latest` on `84dbdfb1…` |
| tag `v0.9.0` | annotated, on commit `8e37a82`, in no branch |
| `main` | still 0.8.3 at `61c5443` |
| GitHub release | none |

The BSR holds two commits for one release. `latest` sits on one created at 00:51:02, a
minute after the workflow's, recording the same source commit. `buf export` of both
gives byte-identical files, so either label resolves to the same schema. The workflow
pushed once, and no other workflow ran in that window; where the second push came from
is not known.

### 4. The repair

1. **Do not re-run the workflow.** It checks out `main`, still at 0.8.3, would bump to
   0.9.0 again, and would fail at the PyPI upload, which refuses a version it already
   has.
2. **Bypass for `ord-service`.** Added with mode `always` to both rulesets, and a
   maintainer's account to the `main` ruleset the same way.
3. **The bump onto `main`.** A fast-forward of `main` to the tagged commit failed with
   GitHub's `fatal error in commit_refs`. That was an operator error, not GitHub: the
   push named `c202c22`, the annotated tag's object, as the source for a branch, and a
   branch cannot point at a tag object. The commit is `v0.9.0^{commit}` = `8e37a82`.
   Rather than retry, the bump landed through
   [ord-schema#1088](https://github.com/open-reaction-database/ord-schema/pull/1088) as
   `654cd4b`. `8e37a82` could not be reused for the pull request: its message carries
   `[skip actions]`, which would have kept the 11 required checks from ever running.
   `654cd4b` and `8e37a82` have the same parent and the same tree, `96c050e`.
4. **The GitHub release**, created from the existing tag with generated notes and a
   line marking the `search` and `nl` extras experimental.

### 5. GitHub hides a commit that only a tag reaches

After the repair, `github.com/.../tree/v0.9.0` and `.../commit/8e37a82…` both returned
404, for signed-in and anonymous requests alike. Everything else about the commit
answered: `git ls-remote`, the REST API, the release page, the tag tarball,
`blob/v0.9.0/pyproject.toml`, `raw.githubusercontent.com`, and
`compare/v0.8.3...v0.9.0`. The two older tags whose commits are in no branch, `v0.5.4`
and `v0.5.5`, had the same 404s.

That matters for more than browsing: the BSR's source link for the release points at
the commit page. Pushing a branch at each commit — `release/v0.9.0`, `release/v0.5.4`,
`release/v0.5.5` — made all six pages return 200 within seconds. The branches have to
stay; deleting one brings its pages' 404s back, and deleting a tag as well would leave
its commit to garbage collection.

Rewriting `main` to put `8e37a82` in its history was considered and declined. It would
need a force-push to `main`, and it would orphan `654cd4b`, which #1088's page records
as its merge.

## Conclusions / next steps

- **The next release is the test.** With `ord-service` at `always` on both rulesets,
  `publish.yml`'s push should go through. If it does not, the same failure lands after
  PyPI and npm again; the repair is finding 4, and re-running the workflow is never it.
- **The ordering is a trade-off worth revisiting.** `publish.yml` publishes before it
  pushes so that `main` never records a version that did not publish. This incident is
  the other failure: a version that published and `main` did not record. Pushing the
  bump and tag first would make that failure a re-runnable one instead, at the cost of
  a `main` that can name an unpublished version.
- **A ruleset change can break a workflow that only runs at release time.** Nothing
  exercises `publish.yml` between releases. Whoever edits the `main` rulesets should
  check `ord-service`'s bypass afterward.
- **Unexplained:** the second BSR push at 00:51:02.

## References

- [ord-schema v0.9.0](https://github.com/open-reaction-database/ord-schema/releases/tag/v0.9.0)
  and [the failed run](https://github.com/open-reaction-database/ord-schema/actions/runs/37083600036).
- [ord-schema#1088](https://github.com/open-reaction-database/ord-schema/pull/1088) — the
  bump, landed through a pull request.
- [Migrating the proto build to buf](../2026-08-26-migrating-the-proto-build-to-buf/README.md)
  — stage 2, the BSR push this release was the first test of.
- [`publish.yml`](https://github.com/open-reaction-database/ord-schema/blob/main/.github/workflows/publish.yml)
  — the workflow, and its reason for publishing before pushing.
- GitHub's REST reference for
  [repository rulesets](https://docs.github.com/en/rest/repos/rules), which defines the
  `always`, `pull_request`, and `exempt` bypass modes.
