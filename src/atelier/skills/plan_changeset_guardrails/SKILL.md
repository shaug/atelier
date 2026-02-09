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

## Steps

1. Resolve target changesets:
   - If `changeset_ids` is provided, use those.
   - Else list children of `epic_id` with `at:changeset`.
1. For each changeset, inspect description/notes:
   - Look for a LOC estimate (e.g., `loc`, `LOC`, `estimate`).
   - If a large estimate is found (>800), ensure approval is recorded.
1. Summarize any violations and send a message to the planner/overseer with
   actionable fixes.
1. Do not block planning; use messages and bead notes instead.

## Verification

- Violations are reported with bead ids and missing guardrail details.
- No beads are blocked or re-labeled automatically.
