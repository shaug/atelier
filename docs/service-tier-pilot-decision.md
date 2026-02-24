# Service Tier Pilot Decision Record (CS3)

- Date: 2026-02-24
- Proposal reference: `docs/service-tier-proposal.md`
- Pilot implementation: `scott/execute-service-tier-pilot-pha-at-1my.1`

## Scope evaluated

- `atelier init` orchestration moved behind service entrypoints.
- Config composition and external-provider resolution moved behind explicit
  request/outcome contracts.
- Command behavior and CLI-visible outcomes remained compatibility targets.

## Evidence summary

### Complexity signal (init/controller boundary)

- `src/atelier/commands/init.py` lines: 213 before, 107 after.
- `if` branches in `src/atelier/commands/init.py`: 19 before, 1 after.
- Service modules in pilot path: 0 before, 3 after.

### Testability signal

- Existing init command integration tests remained in place
  (`tests/atelier/commands/test_init.py`, 13 tests).
- New service-level tests were added for request validation, failure mapping,
  and orchestration seams (`tests/atelier/services/project/test_services.py`, 2
  tests).
- The service layer now accepts injectable collaborators for orchestration,
  which reduces the need to drive full CLI flows to exercise failure paths.

### Bounded-scope signal

- CS2 changed 8 files and ~794 LOC total (adds + deletes), remaining under the
  explicit ~800 LOC split guardrail.
- No broad refactor landed outside the init/config pilot boundary.

## Decision

Decision: **expand with adjustment**.

We should extend the service-tier pattern beyond init/config, but do it in
ordered, bounded slices and address pilot gaps while expanding.

## Why this decision

- Pilot extraction improved controller clarity at the command boundary.
- Service request/result contracts improved deterministic failure handling.
- Unit-level orchestration testing is now feasible without full command setup.
- Remaining gaps are manageable in follow-on scoped changesets.
- Baseline service observability (start/success/failure + duration) is not yet
  standardized.
- Service dependency typing still uses broad callable signatures in places.

## Next changeset scopes

### CS4 candidate: worker startup orchestration service

Target: startup flow only.

- Extract `RunStartupContractService` from
  `src/atelier/worker/session/startup.py` and startup orchestration seams in
  `src/atelier/worker/work_startup_runtime.py`.
- Keep `src/atelier/worker/session/runner.py` controller-thin; preserve startup
  selection behavior and existing lifecycle outcomes.
- Add service tests that assert startup decision sequencing and deterministic
  failure codes.

Guardrails:

- No finalization/publish behavior changes in this changeset.
- Keep CLI/runtime behavior compatibility for existing startup paths.
- Keep diff reviewable; split if expected size exceeds ~800 LOC.

### CS5 candidate: worker finalization orchestration service

Target: finalize/publish orchestration only, after CS4 lands.

- Extract `FinalizeChangesetService` around
  `src/atelier/worker/work_finalization_pipeline.py` and related lifecycle
  decision seams.
- Keep existing git/PR policy behavior unchanged.
- Add service tests for policy-gated outcomes and failure-code mapping.

Guardrails:

- No startup contract rewrites in this changeset.
- No change to existing PR strategy semantics.
- Keep bounded to orchestration; avoid broad helper churn.

## Stop/adjust fallback criteria

If CS4 cannot preserve startup behavior with clear service contracts, pause
expansion and run an "adjust only" pass focused on dependency typing and
observability patterns before attempting CS5.
