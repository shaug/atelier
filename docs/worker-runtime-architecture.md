# Worker Runtime Architecture

This document describes the worker runtime contracts used by `atelier work`.

For service/use-case tier boundaries and migration sequencing, see
`docs/service-tier-proposal.md`.

## Goals

- Keep `src/atelier/commands/work.py` as a thin command controller.
- Keep worker orchestration deterministic via typed runtime ports.
- Keep shell and external-tool interactions behind explicit boundaries.

## Lifecycle Contract

Worker and planner lifecycle decisions share one canonical contract defined in
`src/atelier/lifecycle.py`.

Canonical status model:

- `deferred`: planned/draft work that is not runnable.
- `open`: runnable when graph constraints are satisfied.
- `in_progress`: actively claimed/executing.
- `blocked`: explicitly blocked by an operational dependency.
- `closed`: terminal lifecycle state.

Graph role inference:

- work identity excludes explicit special/non-work records (`at:message`,
  `at:agent`, `at:policy` and matching types).
- epic role is inferred from top-level work nodes (no parent).
- changeset role is inferred from leaf work nodes (no work children).
- a top-level leaf node is both epic and changeset.

Runnable leaf evaluation:

- only work-bead leaves are runnable.
- lifecycle status must resolve to `open` or `in_progress`.
- all dependency blockers must be terminal before execution.

Lifecycle authority:

- canonical status + graph shape are the source of truth for decisions.
- `at:ready` and `cs:*` labels are not used as execution gates.

## Layering

1. **Command layer**

   - `src/atelier/commands/work.py`
   - Normalizes CLI args and delegates to runtime/session orchestration.

1. **Runtime loop**

   - `src/atelier/worker/runtime.py`
   - Handles run modes (`once`, `default`, `watch`) and session loop behavior.
   - Builds runtime dependencies via `build_worker_runtime_dependencies(...)`.

1. **Session runner**

   - `src/atelier/worker/session/runner.py`
   - Orchestrates one worker session end-to-end (startup contract, selection,
     worktree/agent prep, finalize).
   - Consumes grouped typed dependencies from `WorkerRuntimeDependencies`.

1. **Domain services**

   - `src/atelier/worker/work_command_helpers.py` (orchestration glue)
   - `src/atelier/worker/integration_service.py`
   - `src/atelier/worker/finalization_service.py`
   - `src/atelier/worker/reconcile_service.py`
   - Domain modules handle integration/finalization/reconcile mechanics.

1. **External boundaries**

   - `src/atelier/exec.py` typed command runner seam.
   - use `CommandSpec[T]` + `run_typed(...)` for command + parser coupling.
   - `src/atelier/worker/models_boundary.py` validates Beads/PR/review payloads
     before lifecycle decisions.

## Typed Port Contracts

- Runtime dependencies are grouped by concern in `src/atelier/worker/ports.py`:
  - `WorkerInfrastructurePorts`
  - `WorkerLifecyclePorts`
  - `WorkerCommandPorts`
  - `WorkerControlPorts`
- Worker orchestration code avoids weak callable typing (`Callable[..., ...]`)
  and uses explicit protocol signatures instead.

## Public API Contracts

- Runtime helper modules should define public functions directly instead of
  creating `_private` function names and aliasing them in `__all__`.
- `_`-prefixed helpers are module-private and must not be exported.
- Every exported runtime function must include a Google-style docstring with:
  - a clear one-line summary
  - an `Args:` section when the function accepts inputs
  - a `Returns:` section describing the output contract
- `tests/atelier/worker/test_public_api_contract.py` enforces this contract.

## Testing Strategy

- Command tests validate orchestration seams, not deep helper internals.
- Session/runtime tests use fake typed ports for lifecycle behavior.
- Boundary model tests validate malformed payload failures deterministically.
- Command-runner tests cover success/failure/timeout/missing executable and
  request propagation.
- Avoid legacy ad-hoc subprocess helpers in new code; use typed command specs
  and edge validation at adapter boundaries.

## Formatting and Lint Baseline

- Python code lines are limited to 100 characters.
- Comment and docstring prose lines are limited to 80 characters.
- The stricter prose width keeps runtime contracts readable in terminals and
  review tools, while 100-character code lines avoid excessive wrapping for
  typed signatures.
