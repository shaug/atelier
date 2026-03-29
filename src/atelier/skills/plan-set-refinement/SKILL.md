---
name: plan-set-refinement
description: >-
  Enable or update planning refinement requirements on an existing epic or
  changeset by appending an authoritative refinement artifact block.
---

# Plan set refinement

Use this skill to enable refinement at any lifecycle point for existing work.

## Inputs

- issue_id: Epic or changeset id to mutate.
- mode: `requested`, `inherited`, or `project_policy`.
- required: Set `required=true` when claim gating must enforce refinement.
- lineage_root: Required when mode is `inherited`.
- approval fields: Required when `required=true`.
- plan_edit_rounds_max: Refinement planning round budget (default 5).
- post_impl_review_rounds_max: Post-implementation review budget (default 8).

## Steps

1. Run:
   - `python skills/plan-set-refinement/scripts/set_refinement.py --issue-id "<issue_id>" [--mode <mode>] [--required] [--lineage-root <lineage_root>] [--approval-source project_policy|operator --approved-by <principal> --approved-at <iso8601>] [--plan-edit-rounds-max <n>] [--post-impl-review-rounds-max <n>]`
1. Confirm lifecycle is one of `deferred`, `open`, `in_progress`, or `blocked`.
1. Confirm the script appended an authoritative `planning_refinement.v1` note.

## Verification

- The target issue includes a new note block starting with
  `planning_refinement.v1`.
- Required refinement (`required=true`) includes explicit approval evidence.
- Inherited mode records `mode: inherited` and `lineage_root: <id>`.
- Budgets are persisted as `plan_edit_rounds_max` and
  `post_impl_review_rounds_max`.
