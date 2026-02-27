---
name: plan-create-epic
description: >-
  Create a new epic bead with acceptance criteria and planning fields for
  changeset work.
---

# Plan create epic

When a concrete issue is identified, capture it as a deferred epic immediately.
Do not request approval to create or edit deferred beads.

## Inputs

- title: Epic title.
- scope: Short scope summary.
- acceptance: Acceptance criteria.
- changeset_strategy: Guardrails or decomposition rules.
- design: Optional design notes or links.
- no_export: Optional per-bead opt-out from default auto-export.
- beads_dir: Optional Beads store path.

## Steps

1. Create the epic with the script:
   - `python skills/plan-create-epic/scripts/create_epic.py --title "<title>" --scope "<scope>" --acceptance "<acceptance>" [--changeset-strategy "<changeset_strategy>"] [--design "<design>"] [--beads-dir "<beads_dir>"] [--no-export]`
1. The script creates the bead, applies auto-export when enabled by project
   config, sets status to `deferred`, and prints non-fatal retry instructions if
   export fails.
1. If promotion is needed, use `plan-promote-epic`; promotion from `deferred` to
   `open` is the approval gate.
1. Use `--notes` or `--append-notes` for addendums instead of rewriting the
   description.

## Verification

- Epic is created with `at:epic` label (required for epic discovery/indexing).
- Epic status is `deferred` until explicit promotion.
- Acceptance criteria stored in the acceptance field.
- When auto-export is enabled and not opted out, `external_tickets` is updated
  with `direction=exported` and `sync_mode=export`.
