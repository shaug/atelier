---
name: epic_list
description: >-
  List eligible epic beads with summary fields for prompt selection.
---

# Epic list

## Inputs

- show_drafts: Optional boolean to include draft epics.
- beads_dir: Optional Beads store path (defaults to repo .beads).

## Steps

1. Run the formatter script:
   - `python3 scripts/list_epics.py` (or
     `python3 scripts/list_epics.py --show-drafts`)
1. Do not rewrite the script output. Return it verbatim so the overseer sees a
   stable format.

## Required output format

The output must be:

- Header line: `Epics:` or `Draft epics:` (when `show_drafts` is true)
- One epic per line:
  - `- <id> [<status>] <title>`
- Detail line per epic:
  - `  root: <workspace.root_branch|unset> | assignee: <assignee|unassigned>`

## Verification

- Output includes each eligible epic id and title in the required format.
- Draft epics appear only when `show_drafts` is enabled.
