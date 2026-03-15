# Worker Store Migration Contract

Worker startup, lifecycle, hook, queue, and reconcile flows now depend on
`atelier.store` as the worker-side issue-store boundary.

This document narrows that statement to the worker runtime. It explains which
worker entry points are proven against `AtelierStore`, which compatibility seams
remain adapter-local, and which follow-on gaps stay deferred for later epics.

## Proven Worker Boundary

Worker code can treat the following paths as store-backed today:

- startup discovery in `work_startup_runtime` and `queueing`
- epic claim/release and agent hook mutations in `store_adapter`, `claim-epic`,
  `release-epic`, and `hook-status`
- worker inbox and queue reads plus queue claim/read mutations in
  `startup-contract`, `mail-queue-claim`, and `mail-mark-read`
- lifecycle and review metadata mutations in `changeset_state`, `finalize`,
  `reconcile`, and `work_finalization_state`
- descendant changeset discovery and lifecycle summaries used for startup
  selection, no-ready notifications, and reconcile corrections

Those flows should depend on `AtelierStore` plus the typed request/query models
it publishes:

- `ChangesetQuery` and `ReadyChangesetQuery` for startup and lineage reads
- `MessageQuery`, `ClaimMessageRequest`, and `MarkMessageReadRequest` for inbox
  and queue behavior
- `SetAgentBeadHookRequest` and `ClearAgentBeadHookRequest` for hook ownership
- `LifecycleTransitionRequest`, `AppendNotesRequest`, and `UpdateReviewRequest`
  for blocked/finalize/reconcile lifecycle updates

Worker modules should not compose raw `bd` argv for those business flows. Raw
Beads usage remains appropriate only for compatibility-only metadata,
filesystem-oriented worktree state, or lifecycle seams that `atelier.store` does
not publish yet.

## Worker Compatibility Seams

Four worker-visible compatibility seams remain intentional for now:

- agent-bead discovery still scans agent issues by title and compatibility
  description fields before worker code can switch to the store-owned hook
  lookup by bead id
- operator escalations without a work thread (`thread_id=None`) still use the
  legacy `create_message_bead()` path; durable worker/planner coordination stays
  on threaded `atelier.store.CreateMessageRequest`
- worktree and branch metadata writes still go through the legacy Beads helper
  layer because `atelier.store` does not yet publish worktree-path, root-branch,
  or parent-branch mutations
- epic-close and lineage-repair fallback reads still use adapter-local Beads
  helpers when worker teardown must recover from missing parent metadata or
  legacy description fields

Worker logic should rely on the store-backed lifecycle contract first and treat
those compatibility seams as explicit exceptions rather than alternate public
APIs.

## Newly Exposed Worker Gap

`work-done` still closes epics through the deterministic Beads helper rather
than a store-owned epic-close mutation.

That gap is explicit rather than accidental: the current store models publish
changeset lifecycle transitions and hook mutations, but not the composite "close
epic if descendants are terminal, clear the hook, and reconcile external close
state" operation that `work-done` and worker finalize teardown need.

Until that richer epic-finalization semantic lands in `atelier.store`, keep epic
close on the compatibility helper and do not treat it as a reason to bypass the
store for worker claim, queue, hook, or changeset lifecycle work.

## Deferred Work

This worker migration slice leaves the following work deferred:

- publish/integration orchestration migrations onto `atelier.store`
- store-owned worktree and branch metadata mutations for worker session setup
  and teardown
- a store-owned epic-close/finalize semantic so `work-done` can drop its
  compatibility helper
- removal of the unthreaded operator escalation fallback once every worker
  coordination path has a durable epic or changeset thread

No new worker business flow should introduce a fresh Beads-shaped contract. If a
worker path needs more state than `atelier.store` currently exposes, add that
store semantic first and extend the shared parity proof before moving the worker
logic onto it.

## Proof Surface

Representative worker parity is covered by deterministic tests that exercise
worker-facing entry points over both supported Beads backends:

- startup hook, inbox, queue, descendant, and ready-changeset discovery through
  `work_startup_runtime` and `store_adapter`
- epic claim and agent hook set/clear through `store_adapter`
- threaded queue claim/read and lifecycle notes through `store_adapter`
- merged/finalize lifecycle persistence through `changeset_state` and `finalize`

Use this document together with the broader [Atelier Store Contract] when
planning future worker, publish, or review migrations.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier store contract]: ./atelier-store-contract.md
