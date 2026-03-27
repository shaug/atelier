---
name: plan-changeset-guardrails
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
- Each executable path should include explicit planner context: `intent`,
  `rationale`, `non_goals`, `constraints`, `edge_cases`, `related_context`, and
  a done definition.
- Guardrails should be recorded in notes or description when exceptions apply.
- Detect anti-pattern: an epic with exactly one child changeset and no
  decomposition rationale.
- For lifecycle/contract invariant bugs, require an invariant impact map that
  covers mutation entry points, recovery paths, and external side-effect
  adapters.
- If notes/description indicate multiple concern domains (for example lifecycle
  state machine, external provider/ticket sync, dry-run/observability), require
  decomposition into stacked changesets by default.
- Require explicit re-split triggers and planner action (deferred follow-on
  changeset or stack extension) when thresholds or new domains appear.
- Require explicit guidance that review-feedback scope growth is captured
  immediately as deferred follow-on work or stack extension.
- For refined executable units, require `planning.contract_json` and
  `planning.stage: planning_in_review`.
- Surface deterministic errors from the shared refined validator, including
  malformed JSON, missing required payload fields, and completion-definition
  lifecycle conflicts.

## Steps

1. Run the deterministic checker script:
   - `python3 scripts/check_guardrails.py --epic-id <epic_id>`
   - or
     `python3 scripts/check_guardrails.py --changeset-id <id> [--changeset-id <id> ...]`
1. Resolve target changesets:
   - If `changeset_ids` is provided, validate those.
   - Else list leaf work beads (changesets) under `epic_id`.
1. For each changeset, inspect description/notes:
   - Validate the planner authoring contract across the changeset plus inherited
     epic context.
   - Look for a LOC estimate (e.g., `loc`, `LOC`, `estimate`).
   - If a large estimate is found (>800), ensure approval is recorded.
   - When lifecycle/contract invariant terms are present, verify the invariant
     impact map and re-split guidance fields are present.
   - If `execution.strategy: refined`, run shared refined validation and require
     `planning.stage: planning_in_review` before promotion.
1. If an epic has exactly one child changeset, require explicit decomposition
   rationale in the epic or child notes/description.
1. Summarize any violations and send a message to the planner/overseer with
   actionable fixes.
1. Do not block planning; use messages and bead notes instead.

## Verification

- Violations are reported with bead ids and missing guardrail details.
- Missing planner authoring contract sections are reported with actionable field
  names.
- One-child anti-pattern warnings are reported when rationale is missing.
- Cross-cutting invariant violations identify missing impact map coverage,
  decomposition expectations, and re-split handling requirements.
- No beads are blocked or re-labeled automatically.

## Example (Cross-cutting lifecycle bug)

Input notes for `Prevent premature close of active-PR changesets` should include
all of the following:

- Invariant impact map:
  - mutation entry points
  - recovery paths
  - external side-effect adapters
- Concern domains touched and planned stacked changesets.
- Re-split triggers (LOC/files/new concern domain in review).
- Action when triggered: create deferred follow-on changesets or stack
  extension.
- Review feedback rule: scope expansion is captured immediately as deferred
  follow-on work.
