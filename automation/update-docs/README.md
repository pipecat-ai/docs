# update-docs — shared skill

`SKILL.md` here is the canonical instruction set for the `update-docs`
automation that opens documentation PRs against this repository when a source
repo merges a change to public API.

It lives here, in the docs repo, because every source repo's workflow already
checks this repository out. One copy means one place to fix a rule, rather than
one per source repo — the arrangement that previously let two copies drift to
390 and 117 lines with the smaller one missing every improvement made to the
larger.

## How a source repo uses it

The workflow in each source repo checks out `pipecat-ai/docs` at `_docs/` and
points the prompt at `_docs/automation/update-docs/SKILL.md`. The repo keeps
one local file: `.claude/skills/update-docs/SOURCE_DOC_MAPPING.md`, its
**profile**.

```
source repo                            docs repo
├── .github/workflows/update-docs.yml  ├── automation/update-docs/
└── .claude/skills/update-docs/        │   ├── SKILL.md   ← canonical, shared
    └── SOURCE_DOC_MAPPING.md          │   └── README.md  ← this file
        ↑ repo-specific                └── _the docs themselves_
```

## What a profile must provide

`SKILL.md` reads these sections by name. A profile missing one leaves the
corresponding step with nothing to apply, so write all of them.

| Section                    | What it defines                                                                                                                                    | Used by  |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **Scope**                  | Source roots in scope, and what to exclude within them. State exclusions, not an allowlist, so new directories are covered on the day they appear. | Step 3   |
| **Skip list**              | The few genuinely internal files that trigger no doc update. Being a base class or "core architecture" does not qualify.                           | Step 4.1 |
| **Base classes**           | Files whose changes affect many pages, each mapped to _every_ page to check.                                                                       | Step 4.2 |
| **Non-standard locations** | Files whose page can't be derived by pattern.                                                                                                      | Step 4.3 |
| **Patterns**               | Source path → doc path rules covering the bulk of the repo.                                                                                        | Step 4.4 |
| **Search**                 | What symbol to grep for when the tables come up empty.                                                                                             | Step 4.5 |
| **Section vocabulary**     | The sections this repo's pages use, and what each is built from.                                                                                   | Step 5   |
| **Guide directories**      | Doc directories holding prose that cites this repo's API.                                                                                          | Step 7   |
| **New pages**              | Page template, destination path, and _every_ registration step — navigation plus any index or support-matrix page.                                 | Step 8   |

## Writing a profile for a new repo

Start from the mapping in a repo whose shape is closest, then work through the
table above. Two things are worth doing before you trust it:

1. **Resolve backwards.** For a sample of doc pages, ask which source file the
   profile would map to them. A page no rule reaches is a page the automation
   will never update.
2. **Run it on a merged PR.** `workflow_dispatch` accepts a PR number, so a
   known-good change from last month is a free test with a reviewable diff.

The test for whether a file belongs in the Skip list is not "is this internal
architecture" but **"can someone change or observe this without subclassing
it?"** If yes, it has a page somewhere and belongs in a mapping table.

## Changing the shared skill

An edit here changes behavior for every source repo at once — that is the point,
and the risk. Prefer changes that make a rule clearer over ones that add a new
rule, and when adding guidance that only one repo needs, put it in that repo's
profile instead.
