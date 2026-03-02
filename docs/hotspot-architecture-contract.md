# Hotspot Architecture Contract and Complexity Guardrails

- Date: 2026-03-01
- Status: Accepted
- Scope: Beads runtime hotspots and worker startup/finalize/reconcile hotspots
- Change intent: additive contracts and guardrails only; no runtime behavior
  change

## Why this contract exists

The current hotspot modules have grown large enough that migration work needs a
single, explicit contract before moving production logic. This document defines
bounded ownership seams and non-goals for the decomposition stream.

## Non-goals for this contract stage

- No behavior changes to worker startup, finalization, reconcile, or Beads I/O.
- No command-surface changes for `atelier work`, planner, or publish workflows.
- No relocation of service-tier ownership already tracked by `at-u8kq`.

## Beads runtime boundary contract

Current public facade remains `src/atelier/beads.py`. Extraction work can move
implementation details, but this facade must remain a stable import boundary
until the migration is complete.

Target bounded modules and public seams:

- `beads/startup_migration.py`
  - Owns store bootstrapping and migration normalization.
  - Public seam: startup/migration helpers used by planner and worker setup.
- `beads/issue_mutations.py`
  - Owns create/update/close flows and write-path locking.
  - Public seam: typed issue mutation operations used by command/runtime code.
- `beads/queue_messages.py`
  - Owns mail queue listing, claiming, and read-state transitions.
  - Public seam: queue/message operations for planner and worker loops.
- `beads/agent_hooks.py`
  - Owns epic hook claim/release and hook status evaluation.
  - Public seam: deterministic hook transitions consumed by worker startup.
- `beads/external_reconcile.py`
  - Owns external-ticket sync/reconcile helpers.
  - Public seam: explicit reconciliation operations invoked by
    finalize/reconcile workflows.

## Worker orchestration boundary contract

The worker runtime keeps command controllers thin and routes policy decisions
through typed domain seams.

- `worker/session/runner.py`
  - Owns one-iteration orchestration and step ordering only.
  - Must delegate lifecycle gates, publish/finalize actions, and reconcile
    decisions to dedicated services.
- `worker/session/startup.py`
  - Owns startup contract sequencing and runnable-changeset discovery.
  - Must not duplicate lifecycle/review-state policy logic.
- `worker/finalize_pipeline.py`
  - Owns finalization sequencing and persistence choreography.
  - Must consume shared integration/review decisions from common services.
- `worker/reconcile.py`
  - Owns reconcile candidate selection and closure/reopen choreography.
  - Must consume shared lineage/lifecycle policy services.

## Shared decision-service invariants

The decomposition stream must treat these modules as single-source policy
authorities:

- `src/atelier/lifecycle.py`
  - Canonical lifecycle statuses and review-state normalization.
  - Integration-evidence gating (`merged` vs non-terminal review states).
- `src/atelier/dependency_lineage.py`
  - Parent/ancestor lineage resolution for dependency decisions.
- `src/atelier/worker/models_boundary.py`
  - Validation boundary for external/tool payloads before policy evaluation.

No hotspot extraction should fork equivalent decision logic in parallel helper
paths. New modules call these shared services instead.

## Complexity guardrail contract

`python scripts/hotspot_complexity_report.py` generates a baseline report for
hotspot functions. `--check` enforces budgets and fails on regression.

Guardrail targets:

- `src/atelier/beads.py:run_bd_command` span \<= 150, complexity \<= 40
- `src/atelier/beads.py:_raw_bd_json` span \<= 110, complexity \<= 40
- `src/atelier/beads.py:claim_epic` span \<= 120, complexity \<= 36
- `src/atelier/worker/session/runner.py:run_worker_once` span \<= 800,
  complexity \<= 132
- `src/atelier/worker/session/startup.py:run_startup_contract_service` span \<=
  610, complexity \<= 115
- `src/atelier/worker/finalize_pipeline.py:run_finalize_pipeline` span \<= 470,
  complexity \<= 80
- `src/atelier/worker/reconcile.py:reconcile_blocked_merged_changesets` span \<=
  440, complexity \<= 95

CI enforcement points for this contract:

- `scripts/lint-gate.sh` runs
  `python3 scripts/hotspot_complexity_report.py --check`.
- `tests/atelier/test_hotspot_complexity_report.py` validates script behavior
  and the baseline budgets.

## Sequencing boundary vs `at-u8kq`

This hotspot stream and `at-u8kq` are adjacent but distinct:

- This stream owns decomposition contracts and guardrails for Beads runtime and
  worker hotspot orchestration.
- `at-u8kq` continues service-tier extraction and typed collaborator hardening
  for init/config and broader service rollout sequencing.
- If work crosses both boundaries, new follow-on changesets are required instead
  of expanding a single active changeset.
