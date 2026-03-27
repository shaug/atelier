---
name: plan-refined-deliberation
description: >-
  Create rigorous planning contracts for refined execution strategy. Use when a
  changeset needs explicit objective, scope, evidence, and approval metadata
  before workers can claim it.
---

# Plan Refined Deliberation

Use this skill to define *how* planning should be done for high-risk or
cross-cutting work. This is an Atelier-native workflow and does not depend on
external planning skills.

## Inputs

- issue_id: Epic or changeset bead id being planned.
- objective: One clear outcome statement.
- scope: Explicit includes/excludes.
- acceptance_criteria: Measurable outcomes plus evidence artifacts.
- verification_plan: Concrete checks/tests to run.
- risks: Risk plus mitigation pairs.
- escalation_conditions: Conditions that require planner/operator intervention.
- beads_dir: Optional Beads store path.
- repo_dir: Optional repo root override.

## Strategy Contract

For each executable unit that should use refined planning, record:

- `execution.strategy: refined`
- `planning.contract_json: <typed-json-payload>`
- `planning.stage: planning_in_review`

Contract JSON should include:

- `objective`
- `non_goals`
- `acceptance_criteria` (with evidence)
- `scope.includes` and `scope.excludes`
- `verification_plan`
- `risks`
- `escalation_conditions`
- `completion_definition`

## Steps

1. Draft the contract payload with explicit boundaries and testable evidence.
1. Write the metadata fields on the executable unit.
1. Run `plan-changeset-guardrails` and resolve violations.
1. Keep stage at `planning_in_review` until operator promotion approval.
1. Promote with `plan-promote-epic`; approval writes `planning.stage: approved`
   plus planning approval evidence fields.
1. If scope grows during review, create deferred follow-on changesets instead of
   inflating the active unit.

## Verification

- Refined units include `execution.strategy: refined` and valid
  `planning.contract_json`.
- Stage is `planning_in_review` before promotion, then `approved` after explicit
  operator approval.
- Worker startup skips refined units lacking valid approval evidence.
