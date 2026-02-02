---
name: plan_changesets
description: >-
  Create changeset beads under an epic with guardrails for reviewable sizing.
---

# Plan changesets

## Inputs

- epic_id: Parent epic bead id.
- changesets: Ordered list of changeset titles and acceptance criteria.
- guardrails: Size and decomposition rules (line counts, subsystem splits).
- beads_dir: Optional Beads store path.

## Guardrails

- Separate renames from behavioral changes.
- Prefer additive-first changesets.
- Keep changesets reviewable (~200–400 LOC; split when >800 LOC).
- Keep tests with the nearest production change.

## Steps

1. For each changeset, create a bead:
   - `bd create --parent <epic_id> --type task --label at:changeset --label cs:ready --title <title> --acceptance <acceptance>`
1. If the changeset is not ready, use `cs:planned` instead of `cs:ready`.
1. Record guardrails in the changeset description or notes.
1. If a changeset violates guardrails, pause and request explicit approval.

## Verification

- Changeset beads exist under the epic with `at:changeset` labels.
