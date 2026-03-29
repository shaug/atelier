# Trycycle Refinement Convergence Test Plan

Strategy reconciliation:
- The agreed strategy still holds after reading the implementation plan.
- No cost/scope changes are required for approval.
- The only adjustment is to add a repository-local trycycle reference fixture so
  differential tests do not depend on external filesystem paths.

## Harness requirements

1. `H1: Planner Script + Store Integration Harness` (`extend`)
- What it does: Runs planning skill scripts against a real Atelier store built
  on the in-memory Beads backend (and subprocess transport parity where useful).
- What it exposes: Script CLI invocation, stdout/stderr assertions, and post-run
  issue graph/notes inspection via `atelier.store`.
- Estimated complexity: Medium.
- Tests depending on it: 5, 6, 7, 8, 9, 10.

2. `H2: Refinement Artifact Fixture/Oracle Harness` (`new`)
- What it does: Generates canonical and malformed
  `planning_refinement.v1` note blocks and expected winning/evaluation states.
- What it exposes: Programmatic artifact builders, parser inputs, and stable
  expected gate outcomes.
- Estimated complexity: Low.
- Tests depending on it: 13, 14, 15.

3. `H3: Trycycle Reference Snapshot Harness` (`new`)
- What it does: Stores repository-local snapshots of the trycycle planning
  subskill and planning loop prompt/mechanics used as differential references.
- What it exposes: Versioned fixture text and anchor map for doctrine and loop
  parity assertions.
- Estimated complexity: Medium.
- Tests depending on it: 1, 11, 12.

4. `H4: Worker Startup Contract Service Harness` (`extend`)
- What it does: Exercises worker startup selection/claimability behavior through
  `run_startup_contract_service` with typed fake service dependencies.
- What it exposes: User-visible startup result reasons and emitted diagnostics
  without mocking internal lifecycle logic.
- Estimated complexity: Low.
- Tests depending on it: 3, 4, 14.

5. `H5: Skill Packaging + Template Contract Harness` (`extend`)
- What it does: Validates packaged skill presence/frontmatter and planner/worker
  template contract text.
- What it exposes: Projected skill inventory and AGENTS template assertions.
- Estimated complexity: Low.
- Tests depending on it: 2, 12, 16.

Harness implementation order: `H3`, `H2`, `H1`, `H4`, `H5`.

## Test plan

1. **Name**: Convergence map captures full trycycle source inventory and
   doctrine/mechanics mapping
- **Type**: regression
- **Disposition**: new
- **Harness**: `H3`
- **Preconditions**: `docs/trycycle-planning-convergence.md` exists and
  trycycle reference snapshots are present in repo fixtures.
- **Actions**: Run
  `uv run pytest tests/atelier/test_trycycle_planning_convergence.py -k "inventory or mapping" -v`.
- **Expected outcome**: Test passes only when the convergence doc includes each
  required source input, explicit doctrine-vs-mechanics mapping, adaptation
  rationale, and non-goals.
  Source of truth: implementation plan "Trycycle convergence contract" and user
  approved requirement for deep extraction.
- **Interactions**: `docs/trycycle-planning-convergence.md`,
  `docs/behavior.md`, planning/refinement skill docs.

2. **Name**: Planner guidance routes default planning to `planning` and refined
   requests to `refine-plan`
- **Type**: scenario
- **Disposition**: extend
- **Harness**: `H5`
- **Preconditions**: Planner template and new skill docs are present.
- **Actions**: Run
  `uv run pytest tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py -k "planning or refinement" -v`.
- **Expected outcome**: Template and packaged skill assertions confirm
  `planning` is the doctrine default, `refined/refinement` routes to
  `refine-plan`, and `plan-refined-deliberation` is compatibility alias only.
  Source of truth: user-approved trigger semantics and implementation plan
  user-visible behavior.
- **Interactions**: `AGENTS.planner.md.tmpl`, skill packaging/projection.

3. **Name**: Worker startup rejects refined work that lacks approval evidence
   or READY verdict
- **Type**: scenario
- **Disposition**: extend
- **Harness**: `H4`
- **Preconditions**: Refined epic/changeset metadata exists with
  `required=true` and missing/invalid readiness evidence.
- **Actions**: Run
  `uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_session_startup.py -k "refinement and claim" -v`.
- **Expected outcome**: Startup exits without claim and emits stable rejection
  reasons for missing approval or non-`READY` verdict.
  Source of truth: implementation plan "Claim gate invariant".
- **Interactions**: `lifecycle.py`, `worker/selection.py`,
  `worker/session/startup.py`.

4. **Name**: Unrefined startup/claim selection behavior remains unchanged
- **Type**: regression
- **Disposition**: extend
- **Harness**: `H4`
- **Preconditions**: Non-refined epic and ready changeset scenarios from current
  startup suite remain available.
- **Actions**: Run
  `uv run pytest tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py -k "selected_auto or selected_ready_changeset" -v`.
- **Expected outcome**: Existing unrefined paths still resolve actionable epics
  and ready fallback exactly as before.
  Source of truth: implementation plan "Unrefined flows remain behaviorally
  unchanged".
- **Interactions**: Worker startup selector pipeline and ready-changeset
  fallback logic.

5. **Name**: Planner can enable refinement on existing work at any lifecycle
   point
- **Type**: integration
- **Disposition**: new
- **Harness**: `H1`
- **Preconditions**: Existing epic/changeset records in `deferred`, `open`,
  `in_progress`, and `blocked` states.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_set_refinement_script.py -k "lifecycle" -v`.
- **Expected outcome**: `plan-set-refinement` appends authoritative
  refinement metadata with mode/source/budgets and succeeds across allowed
  lifecycle states.
  Source of truth: locked user requirement + implementation plan "Activation and
  approval invariant".
- **Interactions**: `plan-set-refinement` script, store note append and readback.

6. **Name**: Required refinement cannot be enabled without explicit approval
   evidence
- **Type**: boundary
- **Disposition**: new
- **Harness**: `H1`
- **Preconditions**: Existing work item, refinement request with
  `required=true`, missing approval fields.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_set_refinement_script.py -k "approval" -v`.
- **Expected outcome**: Script fails closed with deterministic error output and
  no persisted authoritative block.
  Source of truth: locked user requirement "refinement requires explicit
  approval".
- **Interactions**: refinement activation validation and note persistence.

7. **Name**: Changeset creation inherits refinement lineage from refined parent
- **Type**: integration
- **Disposition**: extend
- **Harness**: `H1`
- **Preconditions**: Parent epic contains authoritative required refinement
  block; sibling unrefined parent exists for control case.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py -k "refinement or inherited" -v`.
- **Expected outcome**: New child changesets under refined lineage carry
  inherited required refinement metadata and budgets; unrefined lineage does not.
  Source of truth: locked user requirement "refinement is viral by lineage".
- **Interactions**: create-epic/create-changeset scripts and store create APIs.

8. **Name**: Splitting overscoped work preserves refinement lineage in all
   descendants
- **Type**: scenario
- **Disposition**: new
- **Harness**: `H1`
- **Preconditions**: Parent changeset exists in refined and unrefined variants.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_split_tasks_script.py -v`.
- **Expected outcome**: `plan-split-tasks` marks all descendants as inherited
  required refinement when parent lineage is refined and leaves unrefined trees
  unmarked.
  Source of truth: locked user requirement on overscope split behavior.
- **Interactions**: split script, graph parent/child writes, refinement metadata.

9. **Name**: Guardrail checks report missing refinement contract evidence
- **Type**: integration
- **Disposition**: extend
- **Harness**: `H1`
- **Preconditions**: Refined changeset exists with incomplete approval/verdict
  fields.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_changeset_guardrails_script.py -k "refinement" -v`.
- **Expected outcome**: Guardrail report flags missing refinement completeness
  details; fully populated refined records pass.
  Source of truth: implementation plan action item for refinement completeness
  checks.
- **Interactions**: `check_guardrails.py`, planner authoring contract checks.

10. **Name**: Promotion preview blocks non-ready refined execution paths and
    surfaces missing sections
- **Type**: scenario
- **Disposition**: extend
- **Harness**: `H1`
- **Preconditions**: Deferred epic with child refined changeset lacking approval
  or `READY` verdict.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_plan_promote_epic_script.py -k "refinement or missing detail" -v`.
- **Expected outcome**: Preview output includes explicit missing refinement
  sections; promotion does not apply lifecycle transition until requirements are
  satisfied.
  Source of truth: implementation plan user-visible promotion/readiness behavior.
- **Interactions**: promote script preview renderer and lifecycle transitions.

11. **Name**: Refine-plan loop honors trycycle verdict protocol and bounded
    rounds
- **Type**: differential
- **Disposition**: new
- **Harness**: `H3`
- **Preconditions**: `refine-plan` runner and prompt-builder modules exist;
  trycycle loop reference snapshot is committed.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_refine_plan_script.py -k "verdict or max_rounds or non_convergence" -v`.
- **Expected outcome**: Defaults and behavior match reference strategy:
  planning-edit cap `5`, canonical verdict tokens
  `READY|REVISED|USER_DECISION_REQUIRED`, fail-closed non-convergence.
  Source of truth: trycycle `SKILL.md`, `subagents/prompt-planning-edit.md`,
  and `orchestrator/run_phase.py`.
- **Interactions**: `refine-plan` loop engine, prompt assembly, result parsing.

12. **Name**: Planning doctrine preserves trycycle planning tone/emphasis, not
    just mechanics
- **Type**: differential
- **Disposition**: new
- **Harness**: `H3`, `H5`
- **Preconditions**: `planning` skill and doctrine reference file exist.
- **Actions**: Run
  `uv run pytest tests/atelier/skills/test_planning_skill_contract.py -v`.
- **Expected outcome**: Doctrine includes required emphasis categories from
  reference planning prose (strategy gate, low bar to replan, high bar to user
  interruption, bite-sized tasking, explicit invariants/contracts).
  Source of truth: user-approved direction and trycycle
  `subskills/trycycle-planning/SKILL.md`.
- **Interactions**: planning skill docs, planner template contract tests.

13. **Name**: Refinement artifact parser deterministically selects the winning
    authoritative block
- **Type**: invariant
- **Disposition**: new
- **Harness**: `H2`
- **Preconditions**: Parser module exists and fixture builder can emit multiple
  ordered note blocks.
- **Actions**: Run
  `uv run pytest tests/atelier/test_planning_refinement.py -k "authoritative or newest" -v`.
- **Expected outcome**: Newest authoritative valid block wins; otherwise newest
  valid block wins; deterministic across permutations.
  Source of truth: implementation plan parser rules.
- **Interactions**: `planning_refinement.py` parse/select functions.

14. **Name**: Malformed or unknown verdict refinement evidence fails closed only
    when refinement is required
- **Type**: boundary
- **Disposition**: new
- **Harness**: `H2`, `H4`
- **Preconditions**: One refined required item and one unrefined control item.
- **Actions**: Run
  `uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/worker/test_session_startup.py -k "malformed or verdict" -v`.
- **Expected outcome**: Required refined work is blocked with stable reason;
  unrefined work remains eligible despite malformed optional metadata.
  Source of truth: parser fail-closed scope in implementation plan.
- **Interactions**: parser + startup claimability evaluation.

15. **Name**: Refinement parser performance avoids catastrophic startup
    regressions
- **Type**: boundary
- **Disposition**: new
- **Harness**: `H2`
- **Preconditions**: Synthetic note payload generator available.
- **Actions**: Run
  `uv run pytest tests/atelier/test_planning_refinement.py -k "performance" -v`.
- **Expected outcome**: Parsing a 1,000-block note payload completes below a
  generous catastrophic-regression threshold (for example `<1s` on CI class
  hardware).
  Source of truth: worker startup repeatedly evaluates claimability and must
  remain practical.
- **Interactions**: startup-critical parsing path.

16. **Name**: New planning/refinement skills ship and validate in projected
    workspaces
- **Type**: regression
- **Disposition**: extend
- **Harness**: `H5`
- **Preconditions**: New skills and alias are added under `src/atelier/skills`.
- **Actions**: Run
  `uv run pytest tests/atelier/test_skills.py tests/atelier/test_skill_frontmatter_validation.py -k "planning or refinement" -v`.
- **Expected outcome**: Packaged skill inventory includes `planning`,
  `refine-plan`, `plan-set-refinement`, and `plan-refined-deliberation`; all
  frontmatter validation passes.
  Source of truth: implementation plan file structure and migration
  compatibility requirement.
- **Interactions**: skill packaging, sync/install, frontmatter validator.

## Coverage summary

Covered action space:
- Planner-facing refinement actions:
  `plan-set-refinement`, `plan-create-epic`, `plan-changesets`,
  `plan-split-tasks`, `plan-changeset-guardrails`, `plan-promote-epic`.
- Planning doctrine and trigger behavior:
  planner template routing, packaged planning/refinement skills, doctrine
  content parity with trycycle references.
- Refine-plan orchestration behavior:
  verdict protocol, bounded loop semantics, fail-closed non-convergence,
  prompt/reference parity.
- Worker-facing claim behavior:
  startup claim rejection for incomplete required refinement and unchanged
  behavior for unrefined work.
- Data contract behavior:
  refinement artifact parsing, winning block selection, malformed input handling,
  and performance envelope.

Explicit exclusions per strategy:
- Real network/API integration with GitHub or external providers is excluded;
  tests stay local and deterministic.
  Risk: provider-specific failures could still appear in production.
- Full live multi-subagent orchestration (real Codex/Kimi/Claude sessions) is
  excluded; tests validate Atelier-side contracts and scripts only.
  Risk: runner integration edge cases may require follow-up in integration envs.
- Visual/manual prompt quality review is excluded; doctrine/tone checks are
  enforced via reproducible text assertions and differential fixtures.
  Risk: subtle prose quality regressions not represented by assertions may slip.
