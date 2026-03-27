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

Focus on planning quality first. Bead write mechanics are secondary.

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

## Planning Method

### 1) Strategy Challenge (before task breakdown)

Before writing tasks, challenge the framing:

- Are we solving the right problem, or just the first visible symptom?
- Is there a simpler path to the operator's actual goal?
- Does the proposed architecture remove complexity, or create it?
- Which assumptions are unvalidated and must be made explicit?

Use a low bar for changing direction. Reframe, re-architect, or replan when a
better path is visible.

Use a high bar for stopping to ask the user. Keep moving unless one of these is
true:

- There is a fundamental conflict between user requirements.
- There is a fundamental conflict between requirements and reality.
- Guessing creates a real risk of harm.

If none of those are true, decide and document the decision in the plan.

### 2) Boundaries Before Tasks

Define the executable boundary before decomposition:

- exact outcome (`objective`)
- explicit non-goals
- included and excluded scope
- invariant/lifecycle constraints
- integration boundaries (external systems, side effects, adapters)
- failure and recovery expectations

### 3) Decompose into Reviewable Units

Break work into independently understandable slices:

- each unit has one clear responsibility
- each unit has a test/verification story
- each unit can be reviewed without global context reload
- file ownership and interfaces are explicit
- defer follow-on work instead of inflating active scope

### 4) Quality Self-Review

A plan is ready only when all checks pass:

- Right problem: Directly advances user outcome.
- Right approach: Simpler alternatives considered and rejected explicitly.
- Explicit assumptions: Unknowns and decisions are recorded.
- Verifiable: Acceptance criteria map to concrete evidence.
- Safe by default: Failure modes, rollback/recovery paths, and escalation are
  defined.
- Executable: A worker can implement without asking for missing intent.

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

1. Run the strategy challenge and record major decisions in notes/description.
1. Draft the contract payload with explicit boundaries and testable evidence.
1. Write the metadata fields on the executable unit.
1. Run `plan-changeset-guardrails` and resolve violations.
1. Keep stage at `planning_in_review` until operator promotion approval.
1. Promote with `plan-promote-epic`; approval writes `planning.stage: approved`
   plus planning approval evidence fields.
1. If scope grows during review, create deferred follow-on changesets instead of
   inflating the active unit.

## Verification

- Plan includes strategy challenge outcomes and explicit assumption handling.
- Refined units include `execution.strategy: refined` and valid
  `planning.contract_json`.
- Stage is `planning_in_review` before promotion, then `approved` after explicit
  operator approval.
- Worker startup skips refined units lacking valid approval evidence.
