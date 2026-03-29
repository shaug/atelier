# Trycycle Refinement Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Converge Atelier planning with trycycle by extracting both trycycle's
planning doctrine and its iterative refinement loop into Atelier-native
`planning` + `refine-plan` skills, with explicit activation, approval evidence,
lineage propagation, and fail-closed worker claim gates.

**Architecture:** Build `planning` as the single planning doctrine skill for all
planning flows (iterative and non-iterative), sourced from both Atelier planner
contract language and trycycle planning prose. Build `refine-plan` as an
opt-in wrapper that runs trycycle-style stateless planning rounds with explicit
verdicts and bounded retries, then persists authoritative refinement evidence in
bead notes. Add a dedicated refinement mutation path (`plan-set-refinement`) so
refinement can be enabled on any epic/changeset at any lifecycle point.

**Tech Stack:** Python 3.11+, Typer/runtime modules, Atelier store/Beads APIs,
projected skill scripts, pytest, markdown templates/docs.

---

## Locked requirements from user decisions

1. Refinement is opt-in per epic/changeset and can be enabled later at any
   lifecycle point.
1. Default budgets match trycycle (`plan_edit_rounds=5`,
   `post_impl_review_rounds=8`) with future project-level configurability.
1. Refinement is viral by lineage. Descendants of refined work remain refined.
1. Worker overscope breakdown uses refinement iff source lineage is refined.
1. Refinement requires explicit approval evidence from project policy or an
   explicit per-item operator request.
1. Convergence includes trycycle planning tone/style and emphasis, not only
   loop mechanics.

## User-visible behavior after cutover

1. `planning` is the primary planning doctrine skill across planner workflows.
1. Requests containing `refined` or `refinement` trigger `refine-plan` before
   promotion/dispatch.
1. Planner can enable refinement on an existing epic/changeset at any time via
   `plan-set-refinement`.
1. Refined beads persist auditable evidence: mode, approval source, budgets,
   rounds used, verdict, and artifact links.
1. Worker claim fails closed when refined work lacks approval evidence or a
   `READY` verdict.
1. Child/split changesets inherit required refinement from refined lineage.
1. Unrefined flows remain behaviorally unchanged.

## Contracts and invariants

### Trycycle convergence contract

The implementation must persist a source-backed mapping doc that includes:

1. A complete inventory of trycycle planning inputs used for convergence
   (planning prompts, planning/edit loop rules, strategy gate language,
   decomposition guidance, convergence semantics).
1. For each source, explicit mapping to:
   - baseline `planning` doctrine (iterative-agnostic), or
   - `refine-plan` orchestration mechanics (iterative).
1. Rationale for each adaptation to Atelier persistence boundaries.
1. Non-goals proving Atelier persistence model is preserved.

### Refinement artifact contract (authoritative note block)

Refinement evidence is stored as append-only note blocks, parsed by
`planning_refinement.py`.

```text
planning_refinement.v1
authoritative: true
mode: requested|inherited|project_policy
required: true|false
lineage_root: <work-id>
approval_status: approved|missing
approval_source: project_policy|operator
approved_by: <principal-id>
approved_at: <ISO-8601>
plan_edit_rounds_max: 5
post_impl_review_rounds_max: 8
plan_edit_rounds_used: <int>
latest_verdict: READY|REVISED|USER_DECISION_REQUIRED
initial_plan_path: <abs-path-or-uri>
latest_plan_path: <abs-path-or-uri>
round_log_dir: <abs-path-or-uri>
```

Parser rules:
- newest `authoritative: true` block wins;
- if none are authoritative, newest valid block wins;
- malformed blocks fail closed only when `required=true` is asserted by any
  winning block in scope;
- unrefined work (no winning refinement block) remains unaffected.

### Activation and approval invariant

Refinement activation must be explicit and durable:

1. `plan-set-refinement` can mark any epic/changeset as refined at any
   lifecycle stage (`deferred|open|in_progress|blocked`).
1. `required=true` demands approval evidence (`approval_status=approved` and
   source/principal/timestamp).
1. `project_policy` mode can satisfy approval automatically only when policy is
   configured and recorded in note evidence.
1. Inherited descendant records copy budgets and mark `mode=inherited`.

### Claim gate invariant

Top-level executable work is not claimable when refinement is required and
either:
- approval evidence is missing, or
- latest verdict is not `READY`.

### Lineage invariant

If a parent executable item has required refinement, any newly created child or
split changeset must carry required inherited refinement.

## Tricky boundaries and risk controls

1. **Doctrine drift risk:** Add contract tests for planning doctrine coverage so
   trycycle tone/style extraction cannot regress to superficial wording.
1. **"Any time" activation gap:** Add explicit mutation skill/script instead of
   relying only on create-time flags.
1. **Approval ambiguity:** Persist machine-readable approval evidence; do not
   infer approval from prose.
1. **Verdict token drift:** Canonical verdicts are
   `READY|REVISED|USER_DECISION_REQUIRED` everywhere.
1. **Backwards compatibility:** Keep `plan-refined-deliberation` as an alias to
   `refine-plan` during migration.
1. **Fail-closed scope:** Only refined markers activate claim blocking.

## File structure (locked decomposition)

### New files

- `docs/trycycle-planning-convergence.md`
  - Source inventory and adaptation map (mechanics + doctrine).
- `src/atelier/planning_refinement.py`
  - Typed parsing/selection/evaluation of refinement note artifacts.
- `src/atelier/skills/planning/SKILL.md`
  - Baseline planning doctrine (Atelier + trycycle merged).
- `src/atelier/skills/planning/references/planning-doctrine.md`
  - Detailed quality rubric and doctrine excerpts.
- `src/atelier/skills/refine-plan/SKILL.md`
  - Iterative wrapper around `planning`.
- `src/atelier/skills/refine-plan/subagents/prompt-planning-initial.md`
  - Initial subagent prompt adapted from trycycle planning flow.
- `src/atelier/skills/refine-plan/subagents/prompt-planning-edit.md`
  - Stateless edit-round prompt with verdict contract.
- `src/atelier/skills/refine-plan/scripts/run_refinement.py`
  - Bounded iterative refinement runner.
- `src/atelier/skills/refine-plan/scripts/prompt_builder/build.py`
  - Prompt assembly helpers adapted from trycycle.
- `src/atelier/skills/refine-plan/scripts/prompt_builder/template_ast.py`
  - Prompt template parser/AST helpers.
- `src/atelier/skills/refine-plan/scripts/prompt_builder/validate_rendered.py`
  - Rendered prompt validation checks.
- `src/atelier/skills/plan-set-refinement/SKILL.md`
  - Explicit activation/update skill for refinement on existing work.
- `src/atelier/skills/plan-set-refinement/scripts/set_refinement.py`
  - Append authoritative refinement artifact notes.
- `src/atelier/skills/plan-refined-deliberation/SKILL.md`
  - Compatibility alias to `refine-plan`.
- `src/atelier/skills/plan-split-tasks/scripts/split_tasks.py`
  - Split helper that propagates refinement lineage.
- `tests/atelier/test_planning_refinement.py`
  - Parser, winning-block, and gate predicate tests.
- `tests/atelier/test_trycycle_planning_convergence.py`
  - Convergence coverage tests for doctrine/mechanics mapping.
- `tests/atelier/skills/test_planning_skill_contract.py`
  - Guards for required baseline planning doctrine sections.
- `tests/atelier/skills/test_refine_plan_script.py`
  - Round-loop and verdict contract tests.
- `tests/atelier/skills/test_plan_set_refinement_script.py`
  - Any-time activation and approval evidence tests.
- `tests/atelier/skills/test_plan_split_tasks_script.py`
  - Inherited refinement propagation tests.

### Modified files

- `src/atelier/models.py`
  - Add planning refinement policy/budget config models.
- `src/atelier/config.py`
  - Resolve default refinement policy and budgets.
- `src/atelier/lifecycle.py`
  - Integrate refinement claim gate evaluation.
- `src/atelier/worker/selection.py`
  - Feed issue payload into refinement-aware claimability checks.
- `src/atelier/templates/AGENTS.planner.md.tmpl`
  - Make `planning` primary doctrine and route `refined/refinement` to
    `refine-plan`; document `plan-set-refinement` usage.
- `src/atelier/templates/AGENTS.worker.md.tmpl`
  - Codify lineage-preserving overscope split behavior.
- `src/atelier/skills/plan-create-epic/SKILL.md`
  - Document create-time refinement options and approval evidence expectations.
- `src/atelier/skills/plan-create-epic/scripts/create_epic.py`
  - Optional create-time refinement note emission.
- `src/atelier/skills/plan-changesets/SKILL.md`
  - Add refinement inheritance rules.
- `src/atelier/skills/plan-changesets/scripts/create_changeset.py`
  - Inherit/write refinement fields from parent.
- `src/atelier/skills/plan-split-tasks/SKILL.md`
  - Switch to deterministic split script contract.
- `src/atelier/skills/plan-promote-epic/SKILL.md`
  - Include refinement readiness in preview/approval checks.
- `src/atelier/skills/plan-promote-epic/scripts/promote_epic.py`
  - Surface refinement readiness diagnostics in preview output.
- `src/atelier/skills/plan-changeset-guardrails/SKILL.md`
  - Add refinement completeness checks.
- `src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py`
  - Validate refinement contract completeness.
- `docs/behavior.md`
  - Document planning/refinement mode semantics and lineage behavior.
- `tests/atelier/test_planner_agents_template.py`
  - Assert planner routing and refinement activation guidance.
- `tests/atelier/test_skills.py`
  - Assert packaged skills/scripts for planning/refinement features.
- `tests/atelier/test_models.py`
  - Config defaults/validation tests for refinement policy.
- `tests/atelier/test_lifecycle.py`
  - Claimability tests for refinement gate.
- `tests/atelier/worker/test_selection.py`
  - Startup selection tests for refined claim filtering.
- `tests/atelier/worker/test_session_startup.py`
  - Session behavior tests around claim gate reasons.
- `tests/atelier/test_worker_agents_template.py`
  - Worker template tests for lineage-aware split behavior.
- `tests/atelier/skills/test_plan_create_epic_script.py`
  - Create-time refinement metadata tests.
- `tests/atelier/skills/test_plan_changesets_script.py`
  - Inheritance tests for child creation.
- `tests/atelier/skills/test_plan_promote_epic_script.py`
  - Promotion preview/refinement readiness tests.
- `tests/atelier/skills/test_plan_changeset_guardrails_script.py`
  - Guardrail checks for refinement contract validity.

## Strategy gate decisions

1. Keep #719 fail-closed gate intent, but ground it in structured refinement
   evidence instead of prose-only checks.
1. Preserve Atelier persistence model (beads + notes) and adapt trycycle
   strategy to that contract.
1. Split doctrine from mechanism: `planning` owns all planning intent;
   `refine-plan` adds iterative evaluation.
1. Add explicit activation path so "refine later" is first-class behavior.

### Task 1: Produce source-backed trycycle convergence map and tests

**Files:**
- Create: `docs/trycycle-planning-convergence.md`
- Create: `tests/atelier/test_trycycle_planning_convergence.py`
- Modify: `docs/behavior.md`

- [ ] **Step 1: Identify or write the failing test**

Add tests that require the convergence doc to include:
- trycycle source inventory,
- doctrine-vs-mechanics mapping,
- Atelier adaptation rationale,
- explicit non-goals.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/test_trycycle_planning_convergence.py -v`
Expected: FAIL because the convergence doc/anchors do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Author the convergence doc with source-backed mappings and update
`docs/behavior.md` with refined planning semantics and lineage policy.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/test_trycycle_planning_convergence.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Polish wording and link definitions.

Run: `uv run pytest tests/atelier/test_trycycle_planning_convergence.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/trycycle-planning-convergence.md docs/behavior.md tests/atelier/test_trycycle_planning_convergence.py
git commit -m "docs(planning): add trycycle convergence source map" -m "- Add a source-backed mapping of trycycle doctrine and iterative mechanics.
- Document Atelier adaptation boundaries and non-goals.
- Add regression tests that prevent shallow convergence drift."
```

### Task 2: Create baseline `planning` doctrine skill

**Files:**
- Create: `src/atelier/skills/planning/SKILL.md`
- Create: `src/atelier/skills/planning/references/planning-doctrine.md`
- Create: `tests/atelier/skills/test_planning_skill_contract.py`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
- Modify: `tests/atelier/test_planner_agents_template.py`
- Modify: `tests/atelier/test_skills.py`

- [ ] **Step 1: Identify or write the failing test**

Add contract tests asserting the baseline planning doctrine includes:
- explicit intent/rationale/non-goals framing,
- strategy gate language,
- low bar for replan / high bar for user interruption,
- bite-sized execution-oriented decomposition guidance.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_planning_skill_contract.py tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py -k planning -v`
Expected: FAIL on missing skill/routing/contract assertions.

- [ ] **Step 3: Write minimal implementation**

Create `planning` as the primary doctrine skill and update planner template so
planning doctrine is skill-owned while template text stays orchestration-only.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_planning_skill_contract.py tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py -k planning -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run: `uv run pytest tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/planning src/atelier/templates/AGENTS.planner.md.tmpl tests/atelier/skills/test_planning_skill_contract.py tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py
git commit -m "feat(planning): add baseline doctrine skill" -m "- Introduce a reusable planning doctrine skill from Atelier + trycycle guidance.
- Route planner behavior through the doctrine skill instead of template-only prose.
- Add contract tests to prevent doctrine drift."
```

### Task 3: Add refinement artifact parser and policy config

**Files:**
- Create: `src/atelier/planning_refinement.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Create: `tests/atelier/test_planning_refinement.py`
- Modify: `tests/atelier/test_models.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests for:
- artifact parse and winning-block selection,
- canonical verdict tokens,
- default 5/8 budgets,
- project policy defaults and validation.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -k refinement -v`
Expected: FAIL because parser/config contract is missing.

- [ ] **Step 3: Write minimal implementation**

Implement typed parser/evaluator helpers and config defaults for refinement
policy and budgets.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -k refinement -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/planning_refinement.py src/atelier/models.py src/atelier/config.py tests/atelier/test_planning_refinement.py tests/atelier/test_models.py
git commit -m "feat(refinement): add artifact contract and policy defaults" -m "- Add typed refinement artifact parsing and gate-evaluation helpers.
- Add project/user policy defaults with trycycle-aligned budgets.
- Add tests for parsing, verdicts, and config validation."
```

### Task 4: Add any-time activation skill for refinement

**Files:**
- Create: `src/atelier/skills/plan-set-refinement/SKILL.md`
- Create: `src/atelier/skills/plan-set-refinement/scripts/set_refinement.py`
- Create: `tests/atelier/skills/test_plan_set_refinement_script.py`
- Modify: `tests/atelier/test_skills.py`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`

- [ ] **Step 1: Identify or write the failing test**

Add tests for:
- enabling refinement on existing epic/changeset regardless of lifecycle state,
- requiring approval evidence when `required=true`,
- inheriting refinement metadata for lineage-derived activation.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_plan_set_refinement_script.py tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -k refinement -v`
Expected: FAIL because activation skill/script is missing.

- [ ] **Step 3: Write minimal implementation**

Implement `plan-set-refinement` and route planner guidance to use it whenever
refinement is requested after initial bead creation.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_plan_set_refinement_script.py tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -k refinement -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run: `uv run pytest tests/atelier/skills/test_plan_set_refinement_script.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-set-refinement src/atelier/templates/AGENTS.planner.md.tmpl tests/atelier/skills/test_plan_set_refinement_script.py tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py
git commit -m "feat(planning): add any-time refinement activation skill" -m "- Add plan-set-refinement for explicit refinement activation on existing work.
- Enforce approval evidence requirements for required refinement mode.
- Update planner guidance and tests for activation routing."
```

### Task 5: Build `refine-plan` iterative wrapper from trycycle mechanics

**Files:**
- Create: `src/atelier/skills/refine-plan/SKILL.md`
- Create: `src/atelier/skills/refine-plan/subagents/prompt-planning-initial.md`
- Create: `src/atelier/skills/refine-plan/subagents/prompt-planning-edit.md`
- Create: `src/atelier/skills/refine-plan/scripts/run_refinement.py`
- Create: `src/atelier/skills/refine-plan/scripts/prompt_builder/build.py`
- Create: `src/atelier/skills/refine-plan/scripts/prompt_builder/template_ast.py`
- Create: `src/atelier/skills/refine-plan/scripts/prompt_builder/validate_rendered.py`
- Create: `tests/atelier/skills/test_refine_plan_script.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests for:
- bounded loop defaults (`max_rounds=5`),
- verdict parsing (`READY|REVISED|USER_DECISION_REQUIRED`),
- per-round artifact emission,
- fail-closed non-convergence behavior.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/skills/test_refine_plan_script.py -v`
Expected: FAIL because runner and prompts do not exist.

- [ ] **Step 3: Write minimal implementation**

Adapt trycycle planning-loop helpers and prompts into `refine-plan` scripts,
with provenance comments that identify source files and commit baseline.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/skills/test_refine_plan_script.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run:
`uv run pytest tests/atelier/skills/test_refine_plan_script.py tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/refine-plan tests/atelier/skills/test_refine_plan_script.py
git commit -m "feat(refine-plan): add trycycle-style iterative planning loop" -m "- Add bounded stateless planning rounds with explicit verdict protocol.
- Adapt trycycle prompt-builder mechanics with provenance comments.
- Add convergence and non-convergence regression tests."
```

### Task 6: Wire create/split/promote/guardrail flows to refinement contract

**Files:**
- Modify: `src/atelier/skills/plan-create-epic/SKILL.md`
- Modify: `src/atelier/skills/plan-create-epic/scripts/create_epic.py`
- Modify: `src/atelier/skills/plan-changesets/SKILL.md`
- Modify: `src/atelier/skills/plan-changesets/scripts/create_changeset.py`
- Modify: `src/atelier/skills/plan-split-tasks/SKILL.md`
- Create: `src/atelier/skills/plan-split-tasks/scripts/split_tasks.py`
- Modify: `src/atelier/skills/plan-promote-epic/SKILL.md`
- Modify: `src/atelier/skills/plan-promote-epic/scripts/promote_epic.py`
- Modify: `src/atelier/skills/plan-changeset-guardrails/SKILL.md`
- Modify: `src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py`
- Modify: `tests/atelier/skills/test_plan_create_epic_script.py`
- Modify: `tests/atelier/skills/test_plan_changesets_script.py`
- Create: `tests/atelier/skills/test_plan_split_tasks_script.py`
- Modify: `tests/atelier/skills/test_plan_promote_epic_script.py`
- Modify: `tests/atelier/skills/test_plan_changeset_guardrails_script.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests for:
- create-time refinement metadata writes,
- lineage inheritance on create/split,
- promotion preview exposing refinement readiness,
- guardrails reporting missing approval/verdict evidence.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py -k refinement -v`
Expected: FAIL because flows are not refinement-aware yet.

- [ ] **Step 3: Write minimal implementation**

Implement refinement-aware behavior across planner authoring scripts, including
lineage inheritance and deterministic split behavior.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_split_tasks_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run: `uv run pytest tests/atelier/skills/test_plan_* -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-create-epic src/atelier/skills/plan-changesets src/atelier/skills/plan-split-tasks src/atelier/skills/plan-promote-epic src/atelier/skills/plan-changeset-guardrails tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_split_tasks_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py
git commit -m "feat(planning): propagate refinement contract through authoring" -m "- Make create/split/promote/guardrail scripts refinement-aware.
- Enforce lineage inheritance and approval/verdict readiness diagnostics.
- Add script-level regression coverage for refinement flows."
```

### Task 7: Enforce worker claim gate and overscope lineage rules

**Files:**
- Modify: `src/atelier/lifecycle.py`
- Modify: `src/atelier/worker/selection.py`
- Modify: `src/atelier/templates/AGENTS.worker.md.tmpl`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
- Modify: `tests/atelier/test_lifecycle.py`
- Modify: `tests/atelier/worker/test_selection.py`
- Modify: `tests/atelier/worker/test_session_startup.py`
- Modify: `tests/atelier/test_worker_agents_template.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests asserting:
- refined work claim rejection without approval or `READY`,
- stable rejection reason tokens,
- overscope split guidance preserves refinement lineage.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py -k refinement -v`
Expected: FAIL due missing gate wiring/template language.

- [ ] **Step 3: Write minimal implementation**

Integrate gate checks in lifecycle/selection and update templates for
lineage-preserving overscope behavior.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py -k refinement -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/lifecycle.py src/atelier/worker/selection.py src/atelier/templates/AGENTS.worker.md.tmpl src/atelier/templates/AGENTS.planner.md.tmpl tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py
git commit -m "feat(worker): fail closed on refined claim requirements" -m "- Reject refined work claims without approval evidence and READY verdict.
- Keep unrefined claim behavior unchanged.
- Add selection/template tests for lineage-aware overscope handling."
```

### Task 8: Add compatibility alias and package-level assertions

**Files:**
- Create: `src/atelier/skills/plan-refined-deliberation/SKILL.md`
- Modify: `tests/atelier/test_skills.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests asserting packaged skills include:
- `planning`,
- `refine-plan`,
- `plan-set-refinement`,
- `plan-refined-deliberation` alias.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/test_skills.py -k "planning or refinement" -v`
Expected: FAIL on missing skills.

- [ ] **Step 3: Write minimal implementation**

Add alias skill that delegates to `refine-plan` and marks deprecation scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/test_skills.py -k "planning or refinement" -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-refined-deliberation tests/atelier/test_skills.py
git commit -m "feat(skills): add refinement compatibility alias" -m "- Add plan-refined-deliberation alias to preserve older entry points.
- Keep refine-plan as the canonical iterative refinement skill.
- Extend packaging tests for new planning/refinement skills."
```

### Task 9: Final verification and quality gates

**Files:**
- Modify: changed files from Tasks 1-8 only when fixes are required.

- [ ] **Step 1: Identify or write the failing test**

No new tests; run full project gates.

- [ ] **Step 2: Run test to verify it fails (if regressions exist)**

Run: `just test`
Expected: PASS or actionable failures to fix.

- [ ] **Step 3: Write minimal implementation**

Fix regressions without weakening valid tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `just test`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run: `just format`
Run: `just lint`
Expected: PASS for both.

- [ ] **Step 6: Commit**

Commit only if Task 9 produced code/doc changes:

```bash
git add -A
git commit -m "chore(planning): reconcile final verification fixes" -m "- Resolve full-suite regressions discovered during final gates.
- Keep changes scoped to quality-gate fixes only."
```

## Completion checklist for this implementation

- [ ] `planning` is the primary doctrine for all planning quality.
- [ ] doctrine convergence includes trycycle tone/style, not only loop mechanics.
- [ ] `refine-plan` runs bounded stateless rounds with canonical verdict tokens.
- [ ] `plan-set-refinement` enables refinement on existing items at any stage.
- [ ] refinement is opt-in, viral by lineage, and approval-gated.
- [ ] worker claim blocks refined work without approval + `READY` evidence.
- [ ] planner/worker templates codify refined trigger and lineage behavior.
- [ ] all tests and repo gates (`just test`, `just format`, `just lint`) pass.
