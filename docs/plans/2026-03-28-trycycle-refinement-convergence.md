# Trycycle Refinement Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Converge Atelier planning with trycycle by extracting both trycycle's
iterative refinement mechanics and its planning prose/tone into Atelier-native
`planning` + `refine-plan` skills, with persisted refinement evidence,
lineage-based propagation, and fail-closed worker claim gates.

**Architecture:** Build a first-class planning doctrine skill (`planning`) from
Atelier planner guidance plus trycycle planning language, then layer a separate
`refine-plan` orchestration skill that adapts trycycle's stateless plan-edit
loop into Atelier's bead persistence model. Treat refinement as explicit policy
(`project` or `per-item`), persist it as structured bead-note artifacts, and
enforce it at worker-claim boundaries so workers cannot execute refined work
without approval and a converged plan verdict.

**Tech Stack:** Python 3.11+, Typer CLI/runtime modules, Atelier store/Beads
APIs, projected skill runtime scripts, pytest, markdown docs and templates.

---

## Locked requirements from user decisions

1. Refinement is opt-in per epic/changeset and may be enabled at any lifecycle
   point.
1. Default budgets match trycycle (`plan-edit rounds=5`,
   `post-implementation review/fix rounds=8`).
1. Refinement is viral by lineage. Descendants of refined work are refined.
1. Worker overscope breakdown uses refinement iff the source lineage is refined.
1. Refinement requires explicit approval, either from project policy or
   per-item request.
1. Convergence must include trycycle planning prose/style, not just mechanics.

## User-visible behavior after cutover

1. Planner has a reusable `planning` skill that defines planning doctrine for
   all agents, not only planner template prose.
1. When operator asks for a "refined" or "refinement" plan, planner runs
   `refine-plan` iterative subagent evaluation before promotion/dispatch.
1. Refined work beads carry auditable refinement artifacts in notes with round
   counts, verdicts, approval evidence, and artifact pointers.
1. Worker claim fails closed for refined work when required approval or
   converged verdict evidence is missing.
1. Split changesets created from refined lineage inherit refinement
   requirements automatically.
1. Unrefined work behavior remains unchanged.

## Contracts and invariants

### Refinement metadata contract (bead notes)

Refinement evidence is stored as note artifacts with deterministic parsing.

```text
planning_refinement.<timestamp>:
authoritative: true
1) mode: requested|inherited|project_policy
2) required: true|false
3) lineage_root: <epic-or-changeset-id>
4) approval:
- status: approved|missing
- source: project_policy|operator
- approved_by: <agent-or-user-id>
- approved_at: <ISO-8601>
5) budgets:
- plan_edit_rounds_max: 5
- post_impl_review_rounds_max: 8
6) rounds_executed:
- plan_edit_rounds_used: <int>
7) latest_verdict: READY|REVISED|USER_DECISION_REQUIRED
8) artifacts:
- initial_plan_path: <abs-path-or-uri>
- latest_plan_path: <abs-path-or-uri>
- round_log_dir: <abs-path-or-uri>
```

Parser rules mirror north-star gate semantics:
- latest `authoritative: true` block wins, else latest block wins.
- malformed refined artifacts fail closed only when refinement is marked
  required.
- unrefined items (no refinement markers) are unaffected.

### Claim gate invariant

A top-level epic is not claimable when refinement is required and either:
- approval status is not `approved`, or
- latest verdict is not `READY`.

### Lineage invariant

If parent executable work has `required: true`, new child changesets must be
created with refinement `mode=inherited`, `required=true`, and copied budgets.

## Tricky boundaries and risk controls

1. **Template vs skill source of truth:** Move planning doctrine into
   `planning` skill. Planner template becomes orchestration/routing only.
1. **Trycycle extraction fidelity:** Vendor/adapt trycycle orchestration helpers
   with provenance comments (`adapted from ...`) and focused API surface.
1. **Backwards compatibility:** Provide `plan-refined-deliberation` alias skill
   delegating to `refine-plan` so older references do not break.
1. **False-positive claim blocks:** Fail closed only when refined markers are
   present; keep legacy unrefined flows unchanged.
1. **Single-cutover safety:** Land parser + metadata writes + claim gate in one
   PR slice so no intermediate state can produce silent bypass.

## File structure (locked decomposition)

### New files

- `docs/plans/2026-03-28-trycycle-refinement-convergence.md`
  - This execution plan.
- `docs/trycycle-planning-convergence.md`
  - Extraction map for trycycle mechanics + prose/tone and Atelier mapping.
- `src/atelier/planning_refinement.py`
  - Typed parser/renderer/validation for `planning_refinement.*` artifacts.
- `src/atelier/skills/planning/SKILL.md`
  - Base planning doctrine (Atelier + trycycle merged, iterative-agnostic).
- `src/atelier/skills/planning/references/planning-doctrine.md`
  - Detailed doctrine language and quality rubric.
- `src/atelier/skills/refine-plan/SKILL.md`
  - Iterative refinement wrapper skill.
- `src/atelier/skills/refine-plan/subagents/prompt-planning-initial.md`
  - Atelier-specific initial planning subagent prompt.
- `src/atelier/skills/refine-plan/subagents/prompt-planning-edit.md`
  - Atelier-specific stateless plan-edit subagent prompt.
- `src/atelier/skills/refine-plan/scripts/run_refinement.py`
  - Main refinement loop runner (Atelier-adapted trycycle flow).
- `src/atelier/skills/refine-plan/scripts/prompt_builder/*.py`
  - Adapted prompt builder internals from trycycle.
- `src/atelier/skills/plan-refined-deliberation/SKILL.md`
  - Compatibility alias/deprecation shim to `refine-plan`.
- `src/atelier/skills/plan-split-tasks/scripts/split_tasks.py`
  - Deterministic split script that propagates refinement lineage.
- `tests/atelier/test_planning_refinement.py`
  - Unit tests for refinement artifact parsing and gate predicates.
- `tests/atelier/skills/test_refine_plan_script.py`
  - Script-level tests for refinement orchestration behavior.
- `tests/atelier/skills/test_plan_split_tasks_script.py`
  - Split lineage propagation tests.

### Modified files

- `src/atelier/models.py`
  - Add planning/refinement user config section and defaults.
- `src/atelier/config.py`
  - Resolve planning refinement defaults and budgets.
- `src/atelier/lifecycle.py`
  - Integrate refinement-required claim gate reasons.
- `src/atelier/worker/selection.py`
  - Pass issue payload details into claimability evaluation.
- `src/atelier/templates/AGENTS.planner.md.tmpl`
  - Route planning through `planning`; refined trigger routes to `refine-plan`.
- `src/atelier/templates/AGENTS.worker.md.tmpl`
  - Overscope split rule references lineage-aware split behavior.
- `src/atelier/skills/plan-create-epic/SKILL.md`
  - Add refinement mode inputs and authoring expectations.
- `src/atelier/skills/plan-create-epic/scripts/create_epic.py`
  - Accept/write refinement contract fields.
- `src/atelier/skills/plan-changesets/SKILL.md`
  - Add refinement inheritance/viral rules.
- `src/atelier/skills/plan-changesets/scripts/create_changeset.py`
  - Inherit/write refinement fields from parent.
- `src/atelier/skills/plan-split-tasks/SKILL.md`
  - Replace raw `bd` calls with deterministic script flow.
- `src/atelier/skills/plan-promote-epic/SKILL.md`
  - Include refinement approval preview checks.
- `src/atelier/skills/plan-promote-epic/scripts/promote_epic.py`
  - Surface refinement contract readiness in preview.
- `src/atelier/skills/plan-changeset-guardrails/SKILL.md`
  - Add refinement contract verification checks.
- `src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py`
  - Validate refinement metadata completeness.
- `src/atelier/skills.py`
  - Package new skills/directories.
- `docs/behavior.md`
  - Document planning/refinement mode semantics.
- `tests/atelier/test_planner_agents_template.py`
  - Assert new planner routing language.
- `tests/atelier/test_skills.py`
  - Assert new packaged skills and scripts.
- `tests/atelier/test_models.py`
  - Config normalization/validation tests for planning refinement settings.
- `tests/atelier/test_lifecycle.py`
  - Claimability tests for refinement gate.
- `tests/atelier/skills/test_plan_create_epic_script.py`
  - Refinement metadata write tests.
- `tests/atelier/skills/test_plan_changesets_script.py`
  - Refinement inheritance tests.
- `tests/atelier/skills/test_plan_changeset_guardrails_script.py`
  - Refinement guardrail tests.
- `tests/atelier/skills/test_plan_promote_epic_script.py`
  - Promotion preview includes refinement readiness.

## Strategy gate decisions

1. Keep #719 gate semantics but anchor them in explicit refinement artifacts,
   not prose-only checks.
1. Use note-based metadata artifacts (existing Beads-compatible medium) instead
   of introducing a new persistence backend.
1. Vendor/adapt trycycle orchestration code into Atelier skills so behavior is
   reproducible and versioned with Atelier.
1. Route all planning doctrine through `planning`; `refine-plan` is a wrapper,
   never the global planning doctrine.

### Task 1: Author trycycle convergence contract and mapping

**Files:**
- Create: `docs/trycycle-planning-convergence.md`
- Modify: `docs/behavior.md`
- Test: `tests/atelier/test_dogfood_doc.py`

- [ ] **Step 1: Identify or write the failing test**

Add/extend a doc contract test to require explicit coverage of:
- trycycle prose extraction,
- trycycle iterative loop extraction,
- Atelier mapping for persistence and gating.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/test_dogfood_doc.py -k convergence -v`
Expected: FAIL because new convergence doc/anchors are missing.

- [ ] **Step 3: Write minimal implementation**

Write `docs/trycycle-planning-convergence.md` with:
- extracted trycycle sources and rationale,
- prose/tone mapping into base `planning` doctrine,
- iterative mechanics mapping into `refine-plan`,
- explicit non-goals (no one-shot replacement of Atelier persistence).

Update `docs/behavior.md` with refined planning mode semantics and lineage
rules.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/test_dogfood_doc.py -k convergence -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Tighten wording, links, and inline reference definitions.

Run: `uv run pytest tests/atelier/test_dogfood_doc.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/trycycle-planning-convergence.md docs/behavior.md tests/atelier/test_dogfood_doc.py
git commit -m "docs(planning): map trycycle convergence contract" -m "- Add a source-backed convergence map for trycycle prose and loop mechanics.
- Document Atelier refined planning mode, lineage propagation, and gating boundaries.
- Add regression checks so convergence intent cannot drift in future edits."
```

### Task 2: Create base `planning` skill and reframe planner template

**Files:**
- Create: `src/atelier/skills/planning/SKILL.md`
- Create: `src/atelier/skills/planning/references/planning-doctrine.md`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
- Modify: `tests/atelier/test_planner_agents_template.py`
- Modify: `tests/atelier/test_skills.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests asserting:
- packaged skills include `planning`,
- planner template routes all planning through `planning`,
- `refine-plan` is invoked for refined/refinement requests.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -v`
Expected: FAIL on missing skill/template assertions.

- [ ] **Step 3: Write minimal implementation**

Create `planning` skill by merging:
- Atelier planner contract sections (intent/rationale/non-goals/etc), and
- trycycle planning doctrine style (explicit decomposition, strategy gate,
  low bar for replan, high bar for user interruption, bite-sized executable
  steps).

Update planner template so `planning` is primary doctrine and template language
is orchestration-focused.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Ensure markdown style and frontmatter validation remain compliant.

Run: `uv run pytest tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/planning src/atelier/templates/AGENTS.planner.md.tmpl tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py
git commit -m "feat(planning): add base planning doctrine skill" -m "- Introduce reusable planning doctrine from Atelier + trycycle prose.
- Reframe planner template to use skills for doctrine and routing.
- Add tests for packaged skill discovery and planner template invariants."
```

### Task 3: Add refinement artifact contract and config policy

**Files:**
- Create: `src/atelier/planning_refinement.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Create: `tests/atelier/test_planning_refinement.py`
- Modify: `tests/atelier/test_models.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests for:
- parsing/selecting authoritative `planning_refinement.*` artifacts,
- default budget values 5/8,
- policy defaults and validation (`project-level required`, `per-item opt-in`).

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -k refinement -v`
Expected: FAIL because contract parser and config models do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement typed refinement contract utilities:
- parse note blocks,
- select authoritative/latest block,
- compute gate readiness (`required`, `approval`, `latest_verdict`).

Add config models/resolvers for planning refinement defaults and budgets.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -k refinement -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Refactor parser helpers for deterministic failure diagnostics.

Run:
`uv run pytest tests/atelier/test_planning_refinement.py tests/atelier/test_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/planning_refinement.py src/atelier/models.py src/atelier/config.py tests/atelier/test_planning_refinement.py tests/atelier/test_models.py
git commit -m "feat(refinement): add planning refinement contract and config" -m "- Add authoritative note artifact parser/selector for planning refinement evidence.
- Add project/user refinement policy defaults and trycycle-aligned round budgets.
- Add regression tests for parser behavior and config normalization."
```

### Task 4: Build `refine-plan` skill by adapting trycycle orchestration

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

Add orchestration tests for:
- bounded round loop (`max=5` default),
- verdict protocol (`READY`, `REVISED`, `USER DECISION REQUIRED`),
- artifact emission for each round,
- deterministic failure when no convergence.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/skills/test_refine_plan_script.py -v`
Expected: FAIL because refine-plan runner does not exist.

- [ ] **Step 3: Write minimal implementation**

Adapt trycycle `run_phase` and prompt-builder mechanics into
`refine-plan/scripts` and wire them to Atelier placeholders and bead paths.

Add provenance comments in adapted files referencing trycycle source paths and
commit baseline.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/skills/test_refine_plan_script.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Refactor runner interfaces to typed request/result dataclasses and deterministic
JSON outputs for downstream scripts.

Run:
`uv run pytest tests/atelier/skills/test_refine_plan_script.py tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/refine-plan tests/atelier/skills/test_refine_plan_script.py
git commit -m "feat(refine-plan): adapt trycycle planning loop for atelier" -m "- Add refine-plan skill with stateless initial/edit planning rounds.
- Adapt trycycle prompt-builder orchestration for Atelier artifact persistence.
- Add loop/verdict tests for convergence and non-convergence behavior."
```

### Task 5: Wire planner authoring scripts for refinement, lineage, and approval

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
- per-item refinement request flags,
- lineage inheritance on child/split creation,
- promotion preview requiring refinement readiness for refined work,
- guardrails reporting missing refinement approvals/verdicts.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py -k refinement -v`
Expected: FAIL due missing refinement wiring.

- [ ] **Step 3: Write minimal implementation**

Update scripts to write/read `planning_refinement.*` artifacts and enforce:
- opt-in at any time,
- viral inheritance,
- explicit approval requirement before open-promotion for refined scope.

Replace raw split instructions with deterministic split script using
store-backed create flows.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_split_tasks_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Refactor duplicate refinement note-writing logic into shared helper usage.

Run:
`uv run pytest tests/atelier/skills/test_plan_* -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-create-epic src/atelier/skills/plan-changesets src/atelier/skills/plan-split-tasks src/atelier/skills/plan-promote-epic src/atelier/skills/plan-changeset-guardrails tests/atelier/skills/test_plan_create_epic_script.py tests/atelier/skills/test_plan_changesets_script.py tests/atelier/skills/test_plan_split_tasks_script.py tests/atelier/skills/test_plan_promote_epic_script.py tests/atelier/skills/test_plan_changeset_guardrails_script.py
git commit -m "feat(planning): propagate refinement lineage through authoring flows" -m "- Add refinement-aware create/split/promote/guardrail script behavior.
- Enforce viral lineage and explicit approval evidence for refined work promotion.
- Add script-level tests for inheritance, readiness previews, and guardrails."
```

### Task 6: Enforce worker claim gate and overscope behavior

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

Add tests asserting claim rejection reason when refined work lacks approval or
`READY` verdict, and template guidance for overscope split lineage behavior.

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py -k refinement -v`
Expected: FAIL due missing gate and template updates.

- [ ] **Step 3: Write minimal implementation**

Integrate refinement gate checks into epic claimability path and selection
filtering. Update worker/planner templates to codify lineage-based split rules.

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py -k refinement -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Ensure rejection reasons are stable machine-readable strings for retry logic.

Run:
`uv run pytest tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/lifecycle.py src/atelier/worker/selection.py src/atelier/templates/AGENTS.worker.md.tmpl src/atelier/templates/AGENTS.planner.md.tmpl tests/atelier/test_lifecycle.py tests/atelier/worker/test_selection.py tests/atelier/worker/test_session_startup.py tests/atelier/test_worker_agents_template.py
git commit -m "feat(worker): fail closed on refined-work claim gate" -m "- Enforce refined-work approval and READY verdict at claimability boundaries.
- Keep unrefined claim behavior unchanged.
- Add template and selection tests for lineage-aware overscope handling."
```

### Task 7: Add compatibility alias and package the new skills

**Files:**
- Create: `src/atelier/skills/plan-refined-deliberation/SKILL.md`
- Modify: `src/atelier/skills.py`
- Modify: `tests/atelier/test_skills.py`

- [ ] **Step 1: Identify or write the failing test**

Add tests asserting packaged skill discovery includes:
- `planning`,
- `refine-plan`,
- `plan-refined-deliberation` alias.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/test_skills.py -k planning -v`
Expected: FAIL on missing skills.

- [ ] **Step 3: Write minimal implementation**

Add alias skill that explicitly routes operators to `refine-plan` and documents
deprecation scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/test_skills.py -k planning -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Ensure frontmatter, naming, and package sync behavior are stable.

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_skill_frontmatter_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-refined-deliberation src/atelier/skills.py tests/atelier/test_skills.py
git commit -m "feat(skills): add refine-plan compatibility alias" -m "- Add plan-refined-deliberation alias that delegates to refine-plan.
- Ensure packaged skill discovery includes new planning/refinement skills.
- Add tests to prevent future skill-packaging drift."
```

### Task 8: Final verification and repo gates

**Files:**
- Modify: all changed files from Tasks 1-7 as needed.

- [ ] **Step 1: Identify or write the failing test**

No new tests. Use full-suite verification as the gate.

- [ ] **Step 2: Run test to verify it fails (if anything regressed)**

Run: `just test`
Expected: Either PASS or actionable failing tests that must be fixed.

- [ ] **Step 3: Write minimal implementation**

Fix any regressions found by full-suite checks without weakening valid tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `just test`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run: `just format`
Run: `just lint`
Expected: PASS for both.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(planning): converge atelier planning with trycycle refinement" -m "- Introduce planning/refine-plan skill architecture with trycycle-derived mechanics and doctrine.
- Persist refinement artifacts, enforce lineage propagation, and fail-closed claim gates.
- Update planner/worker templates, scripts, docs, and tests for a single-cutover rollout."
```

## Completion checklist for this implementation

- [ ] `planning` skill is the primary doctrine for planning quality.
- [ ] `refine-plan` runs bounded stateless plan-edit rounds and persists evidence.
- [ ] refinement trigger semantics are explicit and documented (`refined`/`refinement`).
- [ ] refinement is opt-in, viral by lineage, and approval-gated.
- [ ] worker claim blocks refined work without approval + `READY` evidence.
- [ ] trycycle prose/style has been merged into baseline planning doctrine.
- [ ] all tests, formatting, and lint gates pass.
