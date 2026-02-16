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

1. List epics:
   - `bd list --label at:epic`
1. Exclude epics labeled `at:draft` unless `show_drafts` is true.
1. Display summary fields for each epic:
   - `id`, `status`, `assignee`, `workspace.root_branch`, `title`.

## Verification

- Output includes each eligible epic id and title.
- Draft epics appear only when `show_drafts` is enabled.
