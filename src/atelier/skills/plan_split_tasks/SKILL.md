---
name: plan_split_tasks
description: >-
  Split an epic into changeset beads with dependency-safe labeling.
---

# Plan split tasks

## Inputs

- epic_id: Parent epic bead id.
- tasks: List of changeset titles and acceptance criteria.
- subtasks: Optional nested changesets mapped to a parent changeset.
- beads_dir: Optional Beads store path.

## Steps

1. Create changeset beads under the epic:
   - `bd create --parent <epic_id> --type task --label at:changeset --label cs:planned --title <title> --acceptance <acceptance>`
1. Create nested changesets under a parent changeset when needed:
   - `bd create --parent <changeset_id> --type task --label at:changeset --label cs:planned --title <title> --acceptance <acceptance>`
1. Use `--notes` for follow-up details instead of editing descriptions.

## Verification

- All executable work items are labeled `at:changeset` (never `at:subtask`).
