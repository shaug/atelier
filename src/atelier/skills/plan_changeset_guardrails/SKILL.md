---
name: plan_changeset_guardrails
description: >-
  Validate changeset guardrails for planned work without blocking the planner.
  Use after creating or updating changesets to ensure size and approval notes
  are recorded.
---

# Validate changeset guardrails

## Inputs

- epic_id: Parent epic bead id (optional if changeset_ids provided).
- changeset_ids: Explicit list of changeset bead ids to validate.
- beads_dir: Optional Beads store path.

## Guardrail checks (non-blocking)

- Each changeset should include a LOC estimate in notes.
- If a changeset exceeds the approval threshold (default 800 LOC), notes should
  include an explicit approval record.
- Guardrails should be recorded in notes or description when exceptions apply.
- Detect anti-pattern: an epic with exactly one child changeset and no
  decomposition rationale.

## Steps

1. Run the deterministic checker script:
   - `python3 scripts/check_guardrails.py --epic-id <epic_id>`
   - or
     `python3 scripts/check_guardrails.py --changeset-id <id> [--changeset-id <id> ...]`
1. Resolve target changesets:
   - If `changeset_ids` is provided, validate those.
   - Else list children of `epic_id` with `at:changeset`.
1. For each changeset, inspect description/notes:
   - Look for a LOC estimate (e.g., `loc`, `LOC`, `estimate`).
   - If a large estimate is found (>800), ensure approval is recorded.
1. If an epic has exactly one child changeset, require explicit decomposition
   rationale in the epic or child notes/description.
1. Summarize any violations and send a message to the planner/overseer with
   actionable fixes.
1. Do not block planning; use messages and bead notes instead.

## Verification

- Violations are reported with bead ids and missing guardrail details.
- One-child anti-pattern warnings are reported when rationale is missing.
- No beads are blocked or re-labeled automatically.
