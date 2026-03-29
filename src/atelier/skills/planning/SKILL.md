---
name: planning
description: >-
  Default planning doctrine for Atelier planner sessions, including strategy
  gates and execution-ready decomposition standards.
---

# Planning

Use this skill as the baseline doctrine for all planning flows.

## Doctrine source

- Primary reference: `references/planning-doctrine.md`
- Capture executable intent with explicit `intent, rationale, non-goals`,
  constraints, edge cases, and done definition fields.

## Planning contract

1. Run a strategy gate before decomposition.
1. Keep a low bar for replanning when a better architecture appears.
1. Keep a high bar for user interruption; only interrupt on genuine blockers.
1. Shape bite-sized, execution-oriented tasks with explicit red/green/refactor
   checks.
1. Preserve deterministic, test-first behavior and frequent commit cadence.

## Refinement handoff

- Standard planning requests stay in `planning` doctrine.
- Refined requests route to `refine-plan` for iterative verdict rounds.
- Use `plan-set-refinement` when refinement must be enabled on existing work.
