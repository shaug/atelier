---
name: plan_changesets
description: >-
  Create changeset beads under an epic with guardrails for reviewable sizing.
---

# Plan changesets

Only use this when an epic should be decomposed. If the epic itself is already
within guardrails, keep the epic as the executable changeset instead of creating
children.

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
- Ask for an estimated LOC range per changeset and confirm approval when a
  changeset exceeds ~800 LOC (unless purely mechanical).
- If a changeset is trending >400 LOC, consider splitting before implementation.
- Record the LOC estimate and any explicit approval in notes (use `--notes` or
  `--append-notes`, not `--estimate`).

## Steps

1. For each changeset, create a bead:
   - `bd create --parent <epic_id> --type task --label at:changeset --label cs:ready --title <title> --acceptance <acceptance>`
1. If the changeset is not ready, use `cs:planned` instead of `cs:ready`.
1. Capture an estimated LOC range and record it in notes.
1. If a changeset violates guardrails (especially >800 LOC), pause and request
   explicit approval; record the approval decision in notes.
1. Record guardrails in the changeset description or notes.

## Verification

- Changeset beads exist under the epic with `at:changeset` labels.
- Decomposition happened only when needed for scope/dependency/reviewability.
