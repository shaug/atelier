---
name: refine-plan
description: >-
  Run bounded iterative planning refinement rounds and persist round artifacts
  with canonical verdicts.
---

# Refine plan

Use this skill when planning requests explicitly ask for refined/refinement
behavior before dispatch or promotion.

## Inputs

- initial_plan_path: Absolute path to the current implementation plan.
- output_dir: Directory for round artifacts and latest plan output.
- max_rounds: Optional bounded round cap (default 5).

## Steps

1. Run refinement loop:
   - `python skills/refine-plan/scripts/run_refinement.py --initial-plan-path "<abs-path>" --output-dir "<abs-dir>" [--max-rounds 5]`
1. Use prompt templates:
   - `subagents/prompt-planning-initial.md` for initial-quality framing.
   - `subagents/prompt-planning-edit.md` for iterative edit rounds.
1. Require canonical verdict tokens from each round:
   - `READY`, `REVISED`, `USER_DECISION_REQUIRED`.
1. Fail closed if convergence is not reached before `max_rounds`.

## Verification

- Round artifacts exist under `<output_dir>/rounds/round-XX.json`.
- `latest-plan.md` is written to `<output_dir>`.
- Result status is `ready` only when verdict is `READY`.
- Non-converged runs return `non_converged` and must not be treated as ready.
