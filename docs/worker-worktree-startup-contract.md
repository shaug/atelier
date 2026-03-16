# Worker Worktree Startup Contract

This document defines the worker-side contract for
`src/atelier/worker/session/worktree.py::prepare_worktrees()` and
`src/atelier/worker/session/worktree_fast_path.py::validate_selected_scope()`.

The contract is simple:

- selected-scope validation is the default startup path
- global reconciliation and repair are fallback-only escape hatches
- ambiguous state fails closed instead of mutating local or global state

## Default Path

Worker startup begins with the already selected epic and changeset. The worker
must prove that selected local state is safe before it considers project-wide
repair.

`validate_selected_scope()` inspects only the selected changeset boundary:

- selected changeset metadata from Beads
- the selected epic's mapping file
- the selected worktree path for that changeset
- the checked-out branch only when the mapping and worktree already line up

That ordering is part of the contract. Cheap rejection should happen before any
global ownership scan, lineage synthesis, or repair workflow.

## Outcomes

`SelectedScopeValidationOutcome` defines four allowed decisions:

- `SAFE_REUSE`: the selected mapping, worktree, and branch already agree, so
  startup reuses the selected worktree directly
- `LOCAL_CREATE`: the selected scope has no local lineage yet, so startup
  creates only the selected epic/changeset worktrees and checkout state
- `REQUIRES_FALLBACK_REPAIR`: selected-scope state is present but invalid, so
  startup may enter the existing repair and reconciliation pipeline
- `AMBIGUOUS`: state cannot be trusted safely, so startup stops immediately

Only `SAFE_REUSE` and `LOCAL_CREATE` are fast-path outcomes.

## Fallback Boundary

Global repair is an escape hatch, not the default path. Startup may enter the
fallback path only after selected-scope validation returns
`REQUIRES_FALLBACK_REPAIR`.

When that happens, `prepare_worktrees()` may run:

- targeted startup preflight for prefix-migration residue
- mapping ownership reconciliation
- legacy lineage repair and worktree repair helpers

The fast path must not call those global steps for reusable or locally creatable
selected scope.

## Fail-Closed Rules

`AMBIGUOUS` outcomes block startup. They do not degrade into fallback repair.
Representative cases include:

- mapping ownership that points at a different epic
- mapping files that cannot be parsed
- selected worktree paths that exist but are not git worktrees
- detached or unresolved checked-out branch state

If startup cannot prove safety, it must fail closed and surface a deterministic
reason signal.

## Regression Proof

The contract is enforced by proof-oriented tests:

- `tests/atelier/worker/test_session_worktree_fast_path.py` proves the validator
  stays cheap for reusable and local-create paths and rejects mismatches before
  branch lookup
- `tests/atelier/worker/test_session_worktree.py` proves `prepare_worktrees()`
  reuses or creates selected scope before any global repair, routes invalid
  local state into explicit fallback repair, and keeps ambiguous state
  fail-closed

For the broader worker runtime layering, see [Worker Runtime Architecture].

<!-- inline reference link definitions. please keep alphabetized -->

[worker runtime architecture]: ./worker-runtime-architecture.md
