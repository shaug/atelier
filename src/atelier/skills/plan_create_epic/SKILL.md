---
name: plan_create_epic
description: >-
  Create a new epic bead with acceptance criteria and planning fields for
  changeset work.
---

# Plan create epic

## Inputs

- title: Epic title.
- scope: Short scope summary.
- acceptance: Acceptance criteria.
- changeset_strategy: Guardrails or decomposition rules.
- design: Optional design notes or links.
- beads_dir: Optional Beads store path.

## Steps

1. Create the epic bead:
   - `bd create --type epic --label at:epic --title <title> --acceptance <acceptance> --description "<scope/changeset_strategy>" [--design <design>]`
2. Use `--notes` or `--append-notes` for addendums instead of rewriting the description.

## Verification

- Epic is created with `at:epic` label.
- Acceptance criteria stored in the acceptance field.
