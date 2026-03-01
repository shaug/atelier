---
name: epic-list
description: >-
  List eligible epic beads with summary fields for prompt selection.
---

# Epic list

## Inputs

- show_drafts: Optional boolean to include deferred epics.
- beads_dir: Optional Beads store path (defaults to project-scoped Beads root).

## Steps

1. Run the formatter script:
   - `python3 scripts/list_epics.py` (or
     `python3 scripts/list_epics.py --show-drafts`)
   - Epic discovery is indexed by `at:epic`; this required label defines the
     epic list pool.
1. Do not rewrite the script output. Return it verbatim so the overseer sees a
   stable format.
1. Do not apply execution gating from labels; `cs:*` lifecycle labels are not
   execution gates. Lifecycle buckets come from canonical status + dependency
   context.

## Required output format

The output must be:

- Header line: `Epics by state:`
- One or more state sections:
  - `Draft epics:` (only when `show_drafts` is used and drafts exist)
  - `Open epics:`
  - `In-progress epics:`
  - `Blocked epics:`
  - `Other active epics:` (only when needed)
- One epic per line in each section:
  - `- <id> [<status>] <title>`
- Detail line per epic:
  - `  root: <workspace.root_branch|unset> | assignee: <assignee|unassigned>`

## Verification

- Output includes each eligible epic id and title in the required format.
- Closed epics are excluded.
- Deferred epics appear only when `show_drafts` is enabled.
- Issues without `at:epic` are intentionally excluded from this indexed epic
  listing.
- If `--beads-dir` is explicitly set to a non-project store, the script emits a
  warning with both resolved paths.
