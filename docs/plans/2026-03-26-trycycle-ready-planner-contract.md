# Trycycle-Ready Planner Contract and Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed planner+worker contract so trycycle-targeted
changesets cannot be claimed until a validated plan package and explicit
operator approval are both recorded and auditable.

**Architecture:** Introduce a typed trycycle plan-contract model and shared
validator in core `src/atelier` code, then route planner guardrails,
promotion-time approval capture, and worker startup selection through that one
validator so readiness semantics are identical everywhere. Keep canonical
lifecycle statuses unchanged (`deferred|open|in_progress|blocked|closed`) and
represent staged review with namespaced metadata fields to avoid destabilizing
existing lifecycle logic.

**Tech Stack:** Python 3.11, Pydantic models, Atelier store/beads adapters,
planner skill scripts, worker startup pipeline, pytest.

---

## User-Visible Behavior Contract

1. A changeset becomes trycycle-targeted only when it carries
   `trycycle.targeted: true` metadata.
1. Trycycle-targeted changesets must include a typed plan payload under
   `trycycle.contract_json`.
1. Planner validation must fail closed for trycycle-targeted changesets before
   they are promoted to runnable/open work.
1. Operator approval is explicit and auditable. Promotion records:
   - `trycycle.plan_stage: approved`
   - `trycycle.approved_by`
   - `trycycle.approved_at`
   - `trycycle.approval_message_id`
1. Worker startup refuses to select or resume trycycle-targeted changesets
   whose contract is invalid, missing, or unapproved (including explicit-epic,
   next-changeset, merge-conflict, and review-feedback selection paths).
1. Non-trycycle changesets retain current behavior with no new gating.

## Contracts and Invariants

1. Lifecycle contract remains canonical and unchanged. No new status values are
   added to `LifecycleStatus`.
1. `planning_in_review` is represented as metadata
   (`trycycle.plan_stage: planning_in_review`) rather than lifecycle state.
1. Validation is deterministic and shared. The same checker must be reused by:
   - planner guardrail scripts
   - promotion/approval path
   - worker startup claim gate
1. Worker startup claim gate applies to all claim sources, not only
   next-changeset selection.
1. Approval is mandatory for trycycle-targeted claim eligibility.
1. Missing or malformed contract metadata is treated as non-runnable for
   trycycle-targeted changesets.
1. Completion definition must not conflict with existing finalize semantics:
   close only when PR lifecycle is terminal (`merged|closed`) or when
   `changeset.integrated_sha` proves integration.

## Strategy Gate Decisions (Locked)

1. Use namespaced metadata fields, not a new lifecycle status.
   Reason: adding lifecycle states would touch broad store/lifecycle/finalize
   logic and risks regressions unrelated to #719.
1. Use one typed JSON payload field (`trycycle.contract_json`) plus small,
   auditable metadata fields for stage/approval.
   Reason: typed payload gives strict schema guarantees; small scalar fields
   keep approval evidence easy to inspect with current description-field
   tooling.
1. Reuse one shared core validator for planner and worker paths.
   Reason: avoids drift where planner and worker disagree on readiness.
1. Make worker gate selective (only `trycycle.targeted: true`).
   Reason: preserves existing execution behavior for non-trycycle work.

## File Structure

- Create: `src/atelier/trycycle_contract.py`
  - Typed models, parser/serializer, validation helpers, completion-definition
    conflict checks, evidence summary rendering.
- Create: `tests/atelier/test_trycycle_contract.py`
  - Unit tests for parsing, schema validation, quality checks, and lifecycle
    completion-definition conflict detection.
- Modify: `src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py`
  - Invoke shared trycycle validator, surface deterministic violations.
- Modify:
  `tests/atelier/skills/test_plan_changeset_guardrails_script.py`
  - Add trycycle-targeted valid/invalid/missing-field coverage.
- Modify: `src/atelier/skills/plan-promote-epic/scripts/promote_epic.py`
  - Enforce trycycle validation before promotion, persist approval metadata,
    write evidence summary note, emit approval message.
- Modify: `tests/atelier/skills/test_plan_promote_epic_script.py`
  - Add tests for required approval markers/evidence persistence.
- Modify: `src/atelier/worker/session/startup.py`
  - Extend startup/next-changeset protocols to require trycycle claim
    eligibility and apply the same gate to all startup selection paths.
- Modify: `src/atelier/worker/work_startup_runtime.py`
  - Implement startup + next-changeset service adapter methods using shared
    validator.
- Modify: `tests/atelier/worker/test_session_startup.py`
  - Verify worker skips/rejects unapproved or invalid trycycle-targeted
    changesets across claim paths.
- Modify: `tests/atelier/worker/test_session_next_changeset.py`
  - Verify next-changeset service uses shared trycycle gate for leaf-epic and
    descendant candidate selection.
- Modify: `tests/atelier/worker/test_work_startup_runtime.py`
  - Verify startup runtime adapters use store/contract helpers (not ad hoc
    parsing), including trycycle eligibility adapters.
- Modify: `tests/atelier/worker/test_lifecycle_matrix.py`
  - Add matrix coverage for trycycle claim-gating invariants.
- Modify: `tests/atelier/skills/test_projected_skill_runtime_bootstrap.py`
  - Keep projected runtime fixtures compatible with any new core imports from
    planner scripts.
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
  - Add trycycle-ready planning + explicit approval guidance.
- Modify: `src/atelier/skills/plan-changesets/SKILL.md`
- Modify: `src/atelier/skills/plan-changeset-guardrails/SKILL.md`
- Modify: `src/atelier/skills/plan-promote-epic/SKILL.md`
  - Document new contract fields and approval gate.
- Modify: `docs/behavior.md`
  - Add runtime behavior notes for trycycle-targeted claim gating.

## Cutover and Regression Risks

1. Risk: worker refuses all work due to over-broad gating.
   Mitigation: gate only when `trycycle.targeted: true`; add explicit tests for
   unchanged non-trycycle flow.
1. Risk: startup bypasses gate via review-feedback/merge-conflict selection.
   Mitigation: apply one shared `trycycle_claim_eligible` check before every
   startup return path that yields a concrete changeset id.
1. Risk: planner script import drift in projected skill runtime tests.
   Mitigation: update bootstrap fixture module stubs when introducing
   `trycycle_contract` import.
1. Risk: approval metadata write succeeds partially.
   Mitigation: use store/beads update + read-after-write verification (existing
   atomic verification pattern used in store adapters).
1. Risk: completion-definition checker blocks valid plans.
   Mitigation: codify allowed forms aligned to current worker prompt/finalize
   contract and cover with focused tests.

### Task 1: Add Typed Trycycle Contract Model and Shared Validator

**Files:**
- Create: `src/atelier/trycycle_contract.py`
- Test: `tests/atelier/test_trycycle_contract.py`

- [ ] **Step 1: Identify or write the failing test**

```python
# tests/atelier/test_trycycle_contract.py
from atelier import trycycle_contract


def test_validate_contract_accepts_complete_payload() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            "trycycle.contract_json: {\"objective\":\"...\",...}\n"
        )
    }
    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)
    assert result.ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/atelier/test_trycycle_contract.py -v`
Expected: FAIL (`ImportError` / missing module or missing API).

- [ ] **Step 3: Write minimal implementation**

```python
# src/atelier/trycycle_contract.py
class TrycycleContract(BaseModel):
    objective: str
    non_goals: tuple[str, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    scope: ScopeBoundary
    verification_plan: tuple[str, ...]
    risks: tuple[RiskItem, ...]
    escalation_conditions: tuple[str, ...]
    completion_definition: CompletionDefinition


def evaluate_issue_trycycle_readiness(issue: Mapping[str, object]) -> ReadinessResult:
    # parse description fields
    # if trycycle.targeted != true: return ok/non-targeted
    # parse trycycle.contract_json and stage/approval fields
    # run schema + quality + lifecycle conflict checks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/atelier/test_trycycle_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Tighten parse/normalization boundaries and add dedicated tests for:
- malformed JSON
- missing escalation conditions
- non-testable acceptance criteria (missing evidence)
- conflicting completion definition

Run: `uv run pytest tests/atelier/test_trycycle_contract.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/atelier/test_trycycle_contract.py src/atelier/trycycle_contract.py
git commit -m "feat(planner): add typed trycycle contract validator" \
  -m "- add shared trycycle readiness schema and parser\n- add deterministic readiness validation and diagnostics"
```

### Task 2: Enforce Trycycle Contract in Planner Guardrail Checks

**Files:**
- Modify: `src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py`
- Test: `tests/atelier/skills/test_plan_changeset_guardrails_script.py`

- [ ] **Step 1: Identify or write the failing test**

```python
# tests/atelier/skills/test_plan_changeset_guardrails_script.py

def test_guardrails_flags_trycycle_target_missing_contract() -> None:
    child = {"id": "at-epic.1", "description": "trycycle.targeted: true"}
    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )
    assert any("trycycle.contract_json" in item for item in report.violations)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_plan_changeset_guardrails_script.py -k trycycle -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
from atelier import trycycle_contract

readiness = trycycle_contract.evaluate_issue_trycycle_readiness(issue)
if readiness.targeted and not readiness.contract_present:
    violations.append(f"{issue_id}: missing trycycle.contract_json")
if readiness.targeted and readiness.errors:
    violations.extend(f"{issue_id}: {err}" for err in readiness.errors)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_plan_changeset_guardrails_script.py -k trycycle -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Add test coverage for:
- valid targeted payload (no violations)
- completion-definition conflict violation
- explicit `planning_in_review` stage requirement

Run: `uv run pytest tests/atelier/skills/test_plan_changeset_guardrails_script.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-changeset-guardrails/scripts/check_guardrails.py \
  tests/atelier/skills/test_plan_changeset_guardrails_script.py
git commit -m "feat(planner): validate trycycle-ready contracts in guardrails" \
  -m "- wire guardrail script to shared trycycle readiness validator\n- add deterministic contract violation coverage"
```

### Task 3: Add Promotion-Time Approval Capture and Evidence Persistence

**Files:**
- Modify: `src/atelier/skills/plan-promote-epic/scripts/promote_epic.py`
- Test: `tests/atelier/skills/test_plan_promote_epic_script.py`

- [ ] **Step 1: Identify or write the failing test**

```python
# tests/atelier/skills/test_plan_promote_epic_script.py

def test_promote_epic_blocks_trycycle_target_without_valid_contract(...):
    # targeted child with invalid payload
    # expect SystemExit(1) and explicit trycycle validation error


def test_promote_epic_records_trycycle_approval_metadata(...):
    # targeted valid child + --yes
    # expect description fields include approved_by/approved_at/stage


def test_promote_epic_records_trycycle_approval_metadata_for_epic_single_unit(...):
    # targeted epic with no child changesets + --yes
    # expect same approval fields/message id on epic record
```

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/skills/test_plan_promote_epic_script.py -k trycycle -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# in promote_epic.py before transition_lifecycle
readiness = trycycle_contract.evaluate_issue_trycycle_readiness(child_issue)
if readiness.targeted and not readiness.ok:
    raise RuntimeError(f"{child_id} trycycle readiness failed: {readiness.summary}")

# on --yes for targeted issue
# set: trycycle.plan_stage=approved
# set: trycycle.approved_by=<operator-id>
# set: trycycle.approved_at=<utc iso>
# set: trycycle.approval_message_id=<message bead id>
# append concise evidence note
# create work-threaded approval message and persist message id
# apply updates to every promoted targeted executable record
# (child changesets and epic-as-single-unit when no children exist)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/skills/test_plan_promote_epic_script.py -k trycycle -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Add coverage for:
- non-targeted changesets unchanged
- target with `planning_in_review` stage transitions to `approved`
- persisted approval message id is included in metadata
- single-unit epic target records identical approval metadata

Run: `uv run pytest tests/atelier/skills/test_plan_promote_epic_script.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/skills/plan-promote-epic/scripts/promote_epic.py \
  tests/atelier/skills/test_plan_promote_epic_script.py
git commit -m "feat(planner): require and record trycycle operator approval" \
  -m "- block promotion when trycycle contract validation fails\n- persist approval metadata and planning evidence audit trail"
```

### Task 4: Gate Worker Claim Selection on Trycycle Readiness

**Files:**
- Modify: `src/atelier/worker/session/startup.py`
- Modify: `src/atelier/worker/work_startup_runtime.py`
- Test: `tests/atelier/worker/test_session_startup.py`
- Test: `tests/atelier/worker/test_session_next_changeset.py`
- Test: `tests/atelier/worker/test_work_startup_runtime.py`
- Test: `tests/atelier/worker/test_lifecycle_matrix.py`

- [ ] **Step 1: Identify or write the failing test**

```python
# tests/atelier/worker/test_session_startup.py

def test_next_changeset_skips_unapproved_trycycle_changeset() -> None:
    # first candidate targeted+invalid, second candidate non-targeted valid
    # expect second candidate selected


def test_explicit_epic_with_only_invalid_trycycle_changeset_returns_none() -> None:
    # expect no actionable changeset and startup reason remains fail-closed


def test_review_feedback_selection_rejects_unapproved_trycycle_changeset() -> None:
    # explicit/global review-feedback selection yields a targeted unapproved id
    # expect startup keeps searching or exits with deterministic non-claim reason


def test_merge_conflict_selection_rejects_unapproved_trycycle_changeset() -> None:
    # explicit/global merge-conflict selection yields targeted unapproved id
    # expect startup refuses claim and does not bypass gate
```

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/worker/test_session_startup.py -k trycycle -v`
`uv run pytest tests/atelier/worker/test_session_next_changeset.py -k trycycle -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# startup.NextChangesetService

def trycycle_claim_eligible(self, issue: dict[str, object]) -> tuple[bool, str | None]: ...

# startup.StartupContractService

def trycycle_claim_eligible(self, issue: dict[str, object]) -> tuple[bool, str | None]: ...

# next_changeset_service loop
eligible, reason = service.trycycle_claim_eligible(issue)
if not eligible:
    continue

# run_startup_contract_service paths that return a concrete changeset id
# (explicit/global review-feedback, explicit/global merge-conflict)
# must load the selected issue and apply the same gate before returning.
```

```python
# work_startup_runtime._NextChangesetService

def trycycle_claim_eligible(self, issue):
    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)
    if not result.targeted:
        return True, None
    if result.approved:
        return True, None
    return False, result.summary

# work_startup_runtime._StartupContractService
# delegates to the same helper/validator as _NextChangesetService
```

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/worker/test_session_startup.py -k trycycle -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Add matrix/regression coverage:
- targeted+approved is selectable
- targeted+missing approval is not selectable
- explicit/global review-feedback and merge-conflict selections cannot bypass
  trycycle approval gate
- non-targeted flow unchanged
- fake/test services implement the new protocol method

Run:
- `uv run pytest tests/atelier/worker/test_session_startup.py -v`
- `uv run pytest tests/atelier/worker/test_session_next_changeset.py -v`
- `uv run pytest tests/atelier/worker/test_work_startup_runtime.py -v`
- `uv run pytest tests/atelier/worker/test_lifecycle_matrix.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/atelier/worker/session/startup.py src/atelier/worker/work_startup_runtime.py \
  tests/atelier/worker/test_session_startup.py \
  tests/atelier/worker/test_session_next_changeset.py \
  tests/atelier/worker/test_work_startup_runtime.py \
  tests/atelier/worker/test_lifecycle_matrix.py
git commit -m "feat(worker): fail closed on non-approved trycycle changesets" \
  -m "- add startup claim gate for trycycle contract readiness across all claim paths\n- preserve existing non-trycycle claim behavior"
```

### Task 5: Keep Skill Runtime Bootstrap and Planner Guidance Consistent

**Files:**
- Modify: `tests/atelier/skills/test_projected_skill_runtime_bootstrap.py`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
- Modify: `src/atelier/skills/plan-changesets/SKILL.md`
- Modify: `src/atelier/skills/plan-changeset-guardrails/SKILL.md`
- Modify: `src/atelier/skills/plan-promote-epic/SKILL.md`
- Modify: `docs/behavior.md`
- Test: `tests/atelier/test_planner_agents_template.py`
- Test: `tests/atelier/test_skills.py`

- [ ] **Step 1: Identify or write the failing test**

```python
# tests/atelier/test_skills.py

def test_plan_promote_epic_skill_mentions_trycycle_approval_gate() -> None:
    text = skills.load_packaged_skills()["plan-promote-epic"].text
    assert "trycycle.plan_stage" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Update planner guidance docs/templates to require:
- `@plan-changeset-guardrails` validation for trycycle-targeted work
- explicit operator confirmation and metadata fields
- worker fail-closed expectation for unapproved trycycle changesets

- [ ] **Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/atelier/test_skills.py tests/atelier/test_planner_agents_template.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Ensure projected bootstrap fixtures still satisfy script imports.

Run:
`uv run pytest tests/atelier/skills/test_projected_skill_runtime_bootstrap.py -k guardrails -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/atelier/skills/test_projected_skill_runtime_bootstrap.py \
  src/atelier/templates/AGENTS.planner.md.tmpl \
  src/atelier/skills/plan-changesets/SKILL.md \
  src/atelier/skills/plan-changeset-guardrails/SKILL.md \
  src/atelier/skills/plan-promote-epic/SKILL.md docs/behavior.md \
  tests/atelier/test_planner_agents_template.py tests/atelier/test_skills.py
git commit -m "docs(planner): codify trycycle-ready approval workflow" \
  -m "- align planner template and skill docs with trycycle gating contract\n- update bootstrap and docs coverage for new shared contract usage"
```

### Task 6: Run Full Verification and Land

**Files:**
- Modify: any files touched by fixes discovered during verification.

- [ ] **Step 1: Run focused regression suite**

Run:
```bash
uv run pytest tests/atelier/test_trycycle_contract.py -v
uv run pytest tests/atelier/skills/test_plan_changeset_guardrails_script.py -v
uv run pytest tests/atelier/skills/test_plan_promote_epic_script.py -v
uv run pytest tests/atelier/worker/test_session_startup.py -v
uv run pytest tests/atelier/worker/test_session_next_changeset.py -v
uv run pytest tests/atelier/worker/test_work_startup_runtime.py -v
uv run pytest tests/atelier/worker/test_lifecycle_matrix.py -v
```
Expected: all PASS.

- [ ] **Step 2: Run canonical project gates**

Run:
```bash
just format
just lint
just test
```
Expected: all PASS.

- [ ] **Step 3: If any gate fails, fix root cause (not tests)**

Prefer production/contract fixes over weakening assertions.

- [ ] **Step 4: Re-run failing gate(s) and full required gates**

Re-run whichever command failed, then re-run:
`just format && just lint && just test`
Expected: all PASS.

- [ ] **Step 5: Final review of behavior invariants**

Confirm before merge:
- non-trycycle flows unchanged
- trycycle-targeted flows fail closed unless approved
- approval/evidence metadata is auditable from beads/messages

- [ ] **Step 6: Commit verification fixes**

```bash
git add -A
git commit -m "test(planner): finalize trycycle-ready claim-gate coverage" \
  -m "- close verification gaps across planner validation and worker gating\n- ensure format/lint/test gates pass with fail-closed invariants"
```

## Definition of Done

1. Planner can produce and validate typed trycycle-ready payloads.
1. Promotion path enforces validation and captures explicit approval evidence.
1. Worker startup claim path rejects non-compliant trycycle-targeted changesets.
1. Metadata/messages provide auditable evidence summary + approval record.
1. Existing non-trycycle lifecycle behavior remains unchanged.
1. `just format`, `just lint`, and `just test` pass.
