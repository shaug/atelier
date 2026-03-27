# Trycycle-Ready Planner Contract Test Plan

## Strategy reconciliation
The transcript goal and the implementation plan are aligned: ship a fail-closed
planner/worker contract for trycycle-targeted changesets and record auditable
approval evidence before work becomes runnable.

No strategy changes requiring user approval were identified.

Adjustments made during reconciliation:

1. Expanded worker claim-gate coverage to include global review-feedback and
   global merge-conflict startup paths, not only explicit-epic paths.
   Why: the implementation plan requires all startup claim sources to share the
   same fail-closed gate.
1. Added differential drift checks that compare planner and worker readiness
   outcomes through the shared validator boundary.
   Why: the implementation plan requires one reused validator and deterministic
   readiness semantics.

## Harness requirements
1. **Trycycle metadata fixture builder (new, low complexity)**
   - What it does: builds issue payloads with description-field metadata for
     `trycycle.targeted`, `trycycle.contract_json`, `trycycle.plan_stage`, and
     approval evidence fields.
   - Exposes: helper API for valid, invalid, missing-field, and unapproved
     payload variants.
   - Depends-on tests: 1-9, 17.
1. **Startup protocol fake-service extension (extend, medium complexity)**
   - What it does: updates fake startup services to expose
     `trycycle_claim_eligible(issue) -> (bool, reason)` and configurable
     eligibility outcomes.
   - Exposes: per-issue eligibility maps and captured rejection reasons for
     assertions in claim-path tests.
   - Depends-on tests: 10-16, 18.
1. **Promotion approval-audit harness (extend, medium complexity)**
   - What it does: extends promotion script fakes to capture description-field
     writes, audit message creation, and read-after-write verification paths.
   - Exposes: recorded lifecycle transitions, metadata updates, and approval
     message ids.
   - Depends-on tests: 7-9.
1. **Projected skill bootstrap shim for new core import (extend, low
   complexity)**
   - What it does: updates projected-runtime fake module trees so planner skill
     scripts importing the new core contract module still run in tests.
   - Exposes: repo-src precedence assertions with the new import graph.
   - Depends-on tests: 19.

## Test plan
1. **Name:** Targeted changeset without `trycycle.contract_json` is rejected
   by readiness evaluation
   **Type:** regression
   **Disposition:** new
   **Harness:** Trycycle metadata fixture builder
   **Preconditions:** Issue description contains `trycycle.targeted: true` and
   omits `trycycle.contract_json`.
   **Actions:** Call `evaluate_issue_trycycle_readiness(issue)` from
   `src/atelier/trycycle_contract.py`.
   **Expected outcome:** Result is fail-closed (`ok=False`, targeted true) with
   a deterministic error mentioning missing `trycycle.contract_json`.
   Source: implementation plan, User-Visible Behavior Contract items 1-3 and 6.
   **Interactions:** Description-field parser and contract JSON edge parsing.

1. **Name:** Valid contract in `planning_in_review` is planner-valid but not
   worker-claim-eligible
   **Type:** invariant
   **Disposition:** new
   **Harness:** Trycycle metadata fixture builder
   **Preconditions:** Targeted issue has valid typed contract JSON and
   `trycycle.plan_stage: planning_in_review` with no approval fields.
   **Actions:** Call readiness evaluator and claim-eligibility helper used by
   worker startup.
   **Expected outcome:** Contract validation passes, but claim eligibility is
   false until explicit approval metadata exists.
   Source: implementation plan, User-Visible Behavior Contract items 3-5 and
   Contracts and Invariants item 5.
   **Interactions:** Shared validator output consumed by planner and worker.

1. **Name:** Approval evidence requires all audit fields
   **Type:** boundary
   **Disposition:** new
   **Harness:** Trycycle metadata fixture builder
   **Preconditions:** Targeted issue has valid contract and stage `approved`,
   but one of `approved_by`, `approved_at`, or `approval_message_id` is
   missing/malformed.
   **Actions:** Evaluate readiness for each missing or malformed field case.
   **Expected outcome:** Each case is non-eligible with deterministic
   diagnostics naming the missing evidence field.
   Source: implementation plan, User-Visible Behavior Contract item 4.
   **Interactions:** Field normalization and timestamp parsing logic.

1. **Name:** Completion-definition lifecycle conflicts are rejected
   **Type:** boundary
   **Disposition:** new
   **Harness:** Trycycle metadata fixture builder
   **Preconditions:** Contract completion definition conflicts with finalize
   semantics (for example, allows close without terminal PR state or integrated
   SHA proof).
   **Actions:** Evaluate readiness on conflicting completion definitions.
   **Expected outcome:** Readiness fails with conflict diagnostics; compliant
   definitions pass.
   Source: implementation plan, Contracts and Invariants item 7.
   **Interactions:** Shared completion-definition checker with lifecycle rules.

1. **Name:** Guardrails report fails targeted changesets missing contract
   payload
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Planner script harness (`check_guardrails.py` module entrypoint)
   **Preconditions:** Guardrails target list contains at least one targeted
   changeset without `trycycle.contract_json`.
   **Actions:** Run `_evaluate_guardrails(...)` and `main()` paths.
   **Expected outcome:** Report includes targeted-contract violation text and
   retains existing guardrail reporting format.
   Source: implementation plan Task 2 and User-Visible Behavior Contract items
   2-3.
   **Interactions:** Planner contract checks plus trycycle validator reuse.

1. **Name:** Guardrails accept fully valid targeted planning payload
   **Type:** integration
   **Disposition:** extend
   **Harness:** Planner script harness (`check_guardrails.py`)
   **Preconditions:** Targeted issue has valid contract payload with required
   plan-stage semantics for planner readiness.
   **Actions:** Run guardrail evaluation for targeted child and epic-as-single
   paths.
   **Expected outcome:** No trycycle-targeted violations are emitted for valid
   payloads.
   Source: implementation plan Task 2 and Strategy Gate Decision 3.
   **Interactions:** Cross-check between authoring-contract and trycycle checks.

1. **Name:** Promotion blocks targeted work when contract validation fails
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Promotion approval-audit harness (`promote_epic.py` main path)
   **Preconditions:** Deferred epic has targeted executable unit with invalid or
   missing trycycle contract.
   **Actions:** Run promotion script with and without `--yes`.
   **Expected outcome:** Script exits fail-closed before lifecycle transitions;
   stderr includes deterministic trycycle validation failure.
   Source: implementation plan Task 3 and User-Visible Behavior Contract item 3.
   **Interactions:** Store transition API, preview renderer, shared validator.

1. **Name:** Promotion records complete approval audit metadata for targeted
   child changesets
   **Type:** integration
   **Disposition:** extend
   **Harness:** Promotion approval-audit harness
   **Preconditions:** Deferred epic with deferred targeted child changeset,
   valid contract, explicit `--yes`.
   **Actions:** Run `promote_epic.py --yes`, then inspect persisted metadata.
   **Expected outcome:** Promoted targeted child includes
   `trycycle.plan_stage=approved`, `approved_by`, `approved_at`, and
   `approval_message_id`, and audit evidence is persisted/readable.
   Source: implementation plan User-Visible Behavior Contract item 4 and Task 3.
   **Interactions:** Description-field updates, message-thread persistence,
   lifecycle transition sequencing.

1. **Name:** Promotion records identical approval metadata for epic-as-single
   executable path
   **Type:** integration
   **Disposition:** extend
   **Harness:** Promotion approval-audit harness
   **Preconditions:** Deferred targeted epic has no child changesets and valid
   contract payload.
   **Actions:** Run `promote_epic.py --yes` for single-unit epic path.
   **Expected outcome:** Epic record receives the same approval audit fields and
   evidence message behavior as child-changeset path.
   Source: implementation plan Task 3 and File Structure note for
   epic-as-single-unit coverage.
   **Interactions:** Single-unit execution path in promotion script and store.

1. **Name:** Next-changeset selection skips unapproved targeted candidates
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** Descendant candidate list contains targeted unapproved
   candidate first, followed by eligible non-targeted candidate.
   **Actions:** Run `next_changeset_service(...)`.
   **Expected outcome:** First candidate is rejected by claim gate; second is
   returned.
   Source: implementation plan User-Visible Behavior Contract item 5.
   **Interactions:** Dependency checks, review-state checks, and trycycle gate
   order.

1. **Name:** Explicit-epic startup path fails closed when only targeted
   unapproved work exists
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** `explicit_epic_id` points to claimable epic; next
   executable candidate is targeted and unapproved.
   **Actions:** Run `run_startup_contract_service(...)` with explicit epic mode.
   **Expected outcome:** Startup does not return a runnable changeset and exits
   with deterministic fail-closed reason/output.
   Source: implementation plan User-Visible Behavior Contract item 5 and
   Contracts and Invariants item 6.
   **Interactions:** Explicit epic branch, claimability checks, emission path.

1. **Name:** Explicit merge-conflict selection cannot bypass trycycle approval
   gate
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** PR startup context enabled; merge-conflict selector
   returns targeted unapproved changeset.
   **Actions:** Run startup contract explicit path with
   `select_conflicted_changeset` returning that candidate.
   **Expected outcome:** Startup rejects the candidate and continues scanning or
   exits non-claimable; it does not return the blocked changeset.
   Source: implementation plan User-Visible Behavior Contract item 5.
   **Interactions:** Merge-conflict selector, startup reason routing.

1. **Name:** Explicit review-feedback selection cannot bypass trycycle approval
   gate
   **Type:** scenario
   **Disposition:** extend
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** PR startup context enabled; review-feedback selector
   returns targeted unapproved changeset.
   **Actions:** Run startup contract explicit path with
   `select_review_feedback_changeset`.
   **Expected outcome:** Candidate is rejected by the shared gate; startup does
   not claim it.
   Source: implementation plan User-Visible Behavior Contract item 5.
   **Interactions:** Review-feedback selector and claim gating.

1. **Name:** Global review-feedback and merge-conflict selectors are gated with
   the same trycycle check
   **Type:** integration
   **Disposition:** extend
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** Global selectors return targeted unapproved candidates
   from other epic families.
   **Actions:** Run non-explicit startup contract flow through global selector
   stages.
   **Expected outcome:** Global candidates are rejected identically to explicit
   selectors; no bypass path remains.
   Source: implementation plan Contracts and Invariants item 4 and Task 4.
   **Interactions:** Global selector cache, claimability checks, fallback paths.

1. **Name:** Approved targeted changesets remain selectable across all claim
   sources
   **Type:** invariant
   **Disposition:** new
   **Harness:** Startup protocol fake-service extension
   **Preconditions:** Targeted candidates include complete approved metadata and
   valid contract payload.
   **Actions:** Exercise explicit next-changeset, explicit review-feedback,
   explicit merge-conflict, and global selector paths.
   **Expected outcome:** All paths accept approved targeted candidates when
   other lifecycle constraints are satisfied.
   Source: implementation plan User-Visible Behavior Contract items 4-5.
   **Interactions:** Shared gate with existing claimability predicates.

1. **Name:** Non-trycycle startup behavior remains unchanged
   **Type:** regression
   **Disposition:** extend
   **Harness:** Existing startup/lifecycle matrix harnesses
   **Preconditions:** Issues do not carry `trycycle.targeted: true`.
   **Actions:** Re-run existing startup and lifecycle matrix scenarios.
   **Expected outcome:** Existing non-trycycle selection and lifecycle outcomes
   remain unchanged.
   Source: implementation plan User-Visible Behavior Contract item 6 and
   Contracts and Invariants item 1.
   **Interactions:** Baseline startup selection, lifecycle matrix predicates.

1. **Name:** Shared-validator differential parity across planner and worker
   entrypoints
   **Type:** differential
   **Disposition:** new
   **Harness:** Trycycle metadata fixture builder + startup fake extensions
   **Preconditions:** Matrix of targeted payloads: valid approved, valid
   unapproved, malformed JSON, missing fields, completion conflict.
   **Actions:** Evaluate each payload through
   `trycycle_contract.evaluate_issue_trycycle_readiness`, guardrails integration
   wrapper, promotion preflight path, and worker claim-eligibility adapter.
   **Expected outcome:** All entrypoints agree on eligible vs non-eligible and
   deterministic summary class.
   Source: implementation plan Strategy Gate Decision 3.
   **Interactions:** Cross-module contract reuse and error-summary formatting.

1. **Name:** Runtime adapters call shared validator (no ad hoc parsing)
   **Type:** integration
   **Disposition:** extend
   **Harness:** `test_work_startup_runtime.py` adapter harness
   **Preconditions:** Monkeypatched validator helper records calls; adapter
   service receives targeted and non-targeted issues.
   **Actions:** Call `_NextChangesetService.trycycle_claim_eligible(...)` and
   `_StartupContractService.trycycle_claim_eligible(...)`.
   **Expected outcome:** Both adapters delegate to shared validator and return
   normalized `(eligible, reason)` tuples.
   Source: implementation plan Task 4 and File Structure notes.
   **Interactions:** Runtime adapter boundary to core validator module.

1. **Name:** Projected planner scripts keep bootstrap compatibility after adding
   shared trycycle contract import
   **Type:** integration
   **Disposition:** extend
   **Harness:** Projected skill bootstrap shim
   **Preconditions:** Projected guardrails and promotion scripts run in agent
   home with repo/src precedence test setup.
   **Actions:** Execute projected script `--help` runs under bootstrap tests.
   **Expected outcome:** Scripts import successfully and still resolve repo
   source modules before installed packages.
   Source: implementation plan Cutover and Regression Risks item 3.
   **Interactions:** projected bootstrap, Python path ordering, skill packaging.

1. **Name:** Planner template and skill docs encode trycycle approval gate
   contract
   **Type:** regression
   **Disposition:** extend
   **Harness:** `tests/atelier/test_skills.py` and
   `tests/atelier/test_planner_agents_template.py`
   **Preconditions:** Updated `AGENTS.planner.md.tmpl`,
   `plan-changesets/SKILL.md`, `plan-changeset-guardrails/SKILL.md`, and
   `plan-promote-epic/SKILL.md`.
   **Actions:** Run skill/template content assertions against packaged files.
   **Expected outcome:** Guidance explicitly references trycycle fields,
   approval gate, and worker fail-closed behavior.
   Source: implementation plan Task 5 and User-Visible Behavior Contract items
   3-5.
   **Interactions:** Packaged skill sync/install and template rendering paths.

## Coverage summary
Covered action space:

1. Planner guardrail CLI actions:
   `--epic-id`, `--changeset-id`, targeted contract validation reporting.
1. Promotion CLI actions:
   preview vs `--yes` promotion, targeted validation gate, approval evidence
   persistence for child and epic-as-single paths.
1. Worker startup claim actions:
   explicit epic, next-changeset, review-feedback, merge-conflict, global
   review-feedback, global merge-conflict, and no-bypass fail-closed behavior.
1. Shared validator parity:
   planner, promotion, and worker paths all consume one deterministic contract
   checker.
1. Packaging and documentation surface:
   projected skill bootstrap compatibility plus planner guidance updates.

Explicit exclusions (per current implementation strategy):

1. End-to-end networked GitHub review API behavior is not exercised directly in
   these tests.
   Risk: integration bugs in upstream review fetchers could still affect startup
   candidate discovery before gating.
1. Full `atelier work` subprocess E2E is not expanded for this slice; startup
   contract/service tests remain the primary behavior proof.
   Risk: CLI wiring regressions outside startup contract adapters could require
   follow-up command-level tests.
1. No performance benchmark suite is added because this change is contract
   gating, not throughput-sensitive logic.
   Risk: minimal; catastrophic regressions are still caught by normal test
   runtime and CI gates.
