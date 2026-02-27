---
name: plan-split-tasks
description: >-
  Split an epic into changeset beads with dependency-safe statuses when
  decomposition is needed.
---

# Plan split tasks

Use this only when the epic should be decomposed. If the epic itself is a single
review-sized unit, keep it as the executable changeset.

## Inputs

- epic_id: Parent epic bead id.
- tasks: List of changeset titles and acceptance criteria.
- subtasks: Optional nested changesets mapped to a parent changeset.
- beads_dir: Optional Beads store path.

## Steps

1. Confirm decomposition is necessary for scope, dependency sequencing, or
   reviewability.
1. If decomposition would create exactly one child changeset, keep the epic as
   the executable changeset.
1. Split only when there are multiple executable/reviewable steps; true
   multi-step execution should produce at least two child changesets.
1. Create changeset beads under the epic:
   - `bd create --parent <epic_id> --type task --label at:changeset --title <title> --acceptance <acceptance>`
   - `bd update <new_changeset_id> --status deferred`
1. Create nested changesets under a parent changeset when needed:
   - `bd create --parent <changeset_id> --type task --label at:changeset --title <title> --acceptance <acceptance>`
   - `bd update <new_changeset_id> --status deferred`
1. Use `--notes` for follow-up details instead of editing descriptions.

## Verification

- All executable work items are labeled `at:changeset` (never `at:subtask`).
- No one-child decompositions are present.
