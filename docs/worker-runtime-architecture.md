# Worker Runtime Architecture

This document describes the worker runtime contracts used by `atelier work`.

## Goals

- Keep `src/atelier/commands/work.py` as a thin command controller.
- Keep worker orchestration deterministic via typed runtime ports.
- Keep shell and external-tool interactions behind explicit boundaries.

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

## Testing Strategy

- Command tests validate orchestration seams, not deep helper internals.
- Session/runtime tests use fake typed ports for lifecycle behavior.
- Boundary model tests validate malformed payload failures deterministically.
- Command-runner tests cover success/failure/timeout/missing executable and
  request propagation.
