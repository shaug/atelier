# `atelier work` Breakdown Proposal

## Why this refactor is needed

Current file sizes:

- `src/atelier/commands/work.py`: **5,331 LOC**
- `tests/atelier/commands/test_work.py`: **7,261 LOC**

This command mixes too many responsibilities:

- CLI orchestration
- startup contract and epic selection
- queue/inbox handling
- PR/review feedback detection
- changeset lifecycle transitions
- publish/PR creation behavior
- branch integration/finalization
- reconcile logic
- user prompts and rendering

That creates high regression risk and makes code review/state reasoning harder
than necessary.

## Target architecture

Keep `src/atelier/commands/work.py` as a thin controller and move business logic
to a dedicated worker runtime package.

### 1) New package layout

```text
src/atelier/worker/
  __init__.py
  models.py               # dataclasses and typed return models
  telemetry.py            # trace flag, step/timing reporting, summary rendering
  prompts.py              # worker prompt text generation
  selection.py            # startup contract, epic/changeset selection
  queueing.py             # inbox/queue read/claim/send helpers
  changeset_state.py      # label/status mutations and validation
  review.py               # PR feedback selection/cursor/progress checks
  publish.py              # push/PR creation + strategy decisions
  integration.py          # integration signal checks + branch integration helpers
  finalize.py             # terminal finalize orchestrator
  reconcile.py            # blocked->reconcile scanning and apply
  runtime.py              # run-once/run-loop/watch orchestration
```

`src/atelier/commands/work.py` should only:

- parse args
- resolve project context
- call `worker.runtime.start_worker(...)`
- convert runtime summary to CLI output and exit behavior

### 2) Shared runtime pieces for both `work` and `plan`

To keep organization consistent with future `plan` split:

```text
src/atelier/runtime/
  __init__.py
  telemetry.py            # shared step/timing primitives
  agent_session.py        # common agent startup command wiring
```

Then:

- `worker.telemetry` can delegate to `runtime.telemetry`
- `commands/plan.py` can reuse the same step/timing/session primitives

## Function move map (from current `work.py`)

### A) Models and telemetry

- `StartupContractResult`, `WorkerRunSummary`, `FinalizeResult`,
  `ReconcileResult`, `_PublishSignalDiagnostics`, `_ReviewFeedbackSelection` ->
  `worker/models.py`
- `_trace_enabled`, `_step`, `_report_timings`, `_report_worker_summary` ->
  `worker/telemetry.py` (or `runtime/telemetry.py` + worker wrappers)

### B) Selection/startup contract

- `_filter_epics`, `_sort_by_created_at`, `_sort_by_recency`,
  `_stale_family_assigned_epics`, `_select_epic_prompt`, `_select_epic_auto`,
  `_select_epic_from_ready_changesets`, `_next_changeset`,
  `_run_startup_contract` -> `worker/selection.py`

### C) Queueing/messaging

- `_check_inbox_before_claim`, `_prompt_queue_claim`,
  `_handle_queue_before_claim`, `_send_needs_decision`,
  `_send_planner_notification`, `_send_invalid_changeset_labels_notification`,
  `_send_no_ready_changesets` -> `worker/queueing.py`

### D) Review feedback

- `_changeset_feedback_cursor`, `_persist_review_feedback_cursor`,
  `_capture_review_feedback_snapshot`, `_review_feedback_progressed`,
  `_changeset_in_review_candidate`, `_select_review_feedback_changeset`,
  `_select_global_review_feedback_changeset` -> `worker/review.py`

### E) Publish/PR strategy

- `_changeset_pr_creation_decision`, `_changeset_parent_lifecycle_state`,
  `_changeset_waiting_on_review_or_signals`, `_attempt_push_work_branch`,
  `_attempt_create_draft_pr`, `_render_changeset_pr_body`,
  `_set_changeset_review_pending_state`, `_handle_pushed_without_pr`,
  `_format_publish_diagnostics` -> `worker/publish.py`

### F) Changeset state transitions

- `_find_invalid_changeset_labels`, `_mark_changeset_in_progress`,
  `_mark_changeset_closed`, `_mark_changeset_merged`,
  `_mark_changeset_abandoned`, `_mark_changeset_blocked`,
  `_mark_changeset_children_in_progress`,
  `_close_completed_container_changesets`,
  `_promote_planned_descendant_changesets` -> `worker/changeset_state.py`

### G) Integration/finalization

- `_changeset_integration_signal`, `_epic_root_integrated_into_parent`,
  `_integrate_epic_root_to_parent`, `_finalize_terminal_changeset`,
  `_finalize_epic_if_complete`, `_finalize_changeset`,
  `_recover_premature_merged_changeset`, `_cleanup_epic_branches_and_worktrees`
  -> `worker/finalize.py` and `worker/integration.py`

### H) Reconcile

- `list_reconcile_epic_candidates`, `reconcile_blocked_merged_changesets`,
  `_resolve_hook_agent_bead_for_epic` -> `worker/reconcile.py`

### I) Command/runtime wrapper

- `_run_worker_once`, `start_worker` -> `worker/runtime.py`
- `commands/work.py` becomes controller-only thin entry point.

## Test breakdown proposal

Current tests are tightly coupled to `commands/work.py` internals. Split to
match runtime boundaries:

```text
tests/atelier/commands/test_work.py         # thin controller/wiring only
tests/atelier/worker/test_selection.py
tests/atelier/worker/test_queueing.py
tests/atelier/worker/test_review.py
tests/atelier/worker/test_publish.py
tests/atelier/worker/test_changeset_state.py
tests/atelier/worker/test_finalize.py
tests/atelier/worker/test_reconcile.py
tests/atelier/worker/test_runtime.py
tests/atelier/worker/test_prompts.py
```

Migration guidance for tests:

- Move tests by behavior, not by helper name.
- Keep command tests focused on args, mode dispatch, and top-level summary
  output.
- Keep deep lifecycle/PR logic tests with the extracted module.

## Suggested implementation sequence (changeset-sized)

1. Extract `models.py` + `telemetry.py` + `prompts.py` (no behavior change).
1. Extract `review.py` (existing `work_feedback.py` integration points).
1. Extract `publish.py` (PR strategy + fallback body generation + push
   handling).
1. Extract `changeset_state.py` and replace direct calls.
1. Extract `selection.py` + startup contract.
1. Extract `finalize.py` + `integration.py`.
1. Extract `reconcile.py`.
1. Introduce `worker/runtime.py`; thin `commands/work.py` down to controller.
1. Split test file in parallel per extracted module.

Each step should land with no behavior drift and with tests moved in the same
PR.

## Success criteria

- `commands/work.py` reduced to \<= 400 LOC.
- No module in new worker package > 1,000 LOC; target 200-500.
- `tests/atelier/commands/test_work.py` reduced to command-layer wiring only.
- All worker business logic covered in module-scoped tests.
