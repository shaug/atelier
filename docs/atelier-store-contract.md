# Atelier Store Contract

This document defines the Atelier-owned planning store contract that sits above
`atelier.lib.beads`. It freezes the vocabulary and invariant ownership for
planner and worker logic before the implementation slices land.

## Public Contract

The published Python surface lives in `atelier.store`.

Typed models:

- `EpicRecord`
- `EpicDiscoveryParity`
- `EpicIdentityViolation`
- `ChangesetRecord`
- `DependencyRecord`
- `ExternalTicketLink`
- `ExternalTicketReconcileResult`
- `MessageRecord`
- `HookRecord`
- `ReviewMetadata`
- `LifecycleTransition`

Typed request/query models:

- `EpicQuery`
- `ChangesetQuery`
- `ReadyChangesetQuery`
- `MessageQuery`
- `DependencyMutation`
- `CreateEpicRequest`
- `CreateChangesetRequest`
- `CreateMessageRequest`
- `AppendNotesRequest`
- `ClaimMessageRequest`
- `MarkMessageReadRequest`
- `SetHookRequest`
- `ClearHookRequest`
- `UpdateExternalTicketsRequest`
- `RepairExternalTicketMetadataRequest`
- `UpdateReviewRequest`
- `LifecycleTransitionRequest`

Async store service:

- `AtelierStore`

`AtelierStore` is the single async store boundary for downstream Atelier code.
Later changesets should implement `AtelierStore` itself on top of the reusable
Beads client contract. `atelier.lib.beads.Beads` remains the swappable boundary
underneath, while backend-specific construction and transport details stay out
of this published surface. Internal structural typing aids may still exist
inside adapter modules, but they are not part of `atelier.store` and downstream
code should not target them as an alternate public contract.

The contract is intentionally backend-neutral. It does not expose `bd` commands,
`BEADS_DIR`, Dolt layout, filesystem probes, transport details, or startup
marker paths.

Planner startup and discovery migrations may also rely on:

- `AtelierStore.epic_discovery_parity()`
- `AtelierStore.reconcile_reopened_external_tickets()`
- `AtelierStore.reconcile_closed_external_tickets()`
- `EpicRecord.root_branch`
- `DependencyRecord.status`

## Atelier-Owned Invariants

Atelier owns the business semantics below even when the concrete store
implementation is backed by Beads:

- Lifecycle status uses the canonical set
  `deferred|open|in_progress|blocked|closed`.
- Legacy Beads `tombstone` remains backend-specific deletion state.
  `AtelierStore` does not widen the public lifecycle vocabulary for it: direct
  typed reads normalize `tombstone` to `closed`, and open
  discovery/inbox/queue/ready queries exclude those records from actionable
  results.
- Review state is tracked separately from lifecycle state using the canonical PR
  lifecycle values `pushed|draft-pr|pr-open|in-review|approved|merged|closed`.
- Changesets may carry branch metadata plus review and integration metadata
  without exposing how the backend persists those fields.
- External ticket metadata is a store-owned persistence concern. Provider
  adapters own remote import/export/sync behavior, while `AtelierStore` owns the
  normalized persisted link shape, provider labels, and drift timestamps
  (`state_updated_at`, `content_updated_at`, `notes_updated_at`,
  `last_synced_at`) plus metadata repair and exported-ticket lifecycle
  reconciliation when legacy history recovery or lifecycle drift needs a
  store-owned owner.
- Dependency satisfaction is an Atelier decision. Adapters may persist raw
  dependency edges, but whether a dependency counts as satisfied is owned by
  Atelier lifecycle policy.
- Durable message routing is an Atelier contract: store-level messages are
  `work-threaded` on `epic|changeset` threads. `thread_id`, `thread_kind`,
  `audience`, `blocking`, `reply_to`, queue claim metadata, and read-state
  transitions are stable store concepts. Legacy assignee or queue compatibility
  routing may still be projected inside adapter-local startup helpers, but those
  startup-only compatibility projections are not part of `atelier.store`.
  Assignee-delivery hints remain adapter-local compatibility state rather than
  published store vocabulary.
- Hook ownership is an Atelier contract binding one agent to one epic.
- Lifecycle transitions are store mutations with canonical target states, not
  free-form status edits.

## Beads-Client Responsibilities

`atelier.lib.beads` remains the authority for lower-level concerns:

- supported `bd` command inventory
- version and capability probing
- raw issue JSON decoding
- subprocess transport and timeout behavior
- startup readiness probing and storage-specific recovery signals
- concrete Beads persistence details such as description fields, labels, slots,
  and backend storage layout

The eventual `AtelierStore` implementation may use those lower-level details
internally, but they are not part of the Atelier store contract.

## Dual-Backend Proof

The store contract is now proven against both supported `Beads` backends:

- `InMemoryBeadsClient` for deterministic semantic fixtures
- `SubprocessBeadsClient` for the process-backed command contract

The shared proof runs the same `AtelierStore` read and mutation flows over both
backends. Representative read coverage includes epic discovery, changeset
listing and ready discovery, message listing, hook lookup, branch metadata,
review/dependency state decoding, and external ticket metadata reads.
Representative mutation coverage includes epic and changeset authoring, review
updates, external ticket metadata replacement and repair, note appends,
lifecycle transitions, message create/claim/read, and agent hook set/clear.

This proof freezes one architecture shape: a single Atelier-owned store boundary
implemented on top of multiple `Beads` backends. Future backend additions must
extend the same `AtelierStore` contract rather than introducing a new public
store surface for planner or worker code.

## Downstream Migration Contract

Planner, worker, and publish migrations should depend on `atelier.store` and its
typed models/requests, not on raw Beads issue payloads.

Downstream epics can rely on the following store surface today:

- `AtelierStore`
- `EpicRecord`, `ChangesetRecord`, `MessageRecord`, `HookRecord`
- `ReviewMetadata`, `ExternalTicketLink`, `DependencyRecord`,
  `LifecycleTransition`
- the request/query models in `atelier.store.contract`, including
  `CreateEpicRequest`, `CreateChangesetRequest`, `AppendNotesRequest`,
  `UpdateReviewRequest`, `UpdateExternalTicketsRequest`,
  `RepairExternalTicketMetadataRequest`, `LifecycleTransitionRequest`,
  `CreateMessageRequest`, `ClaimMessageRequest`, `MarkMessageReadRequest`,
  `SetHookRequest`, and `ClearHookRequest`
- shared dual-backend parity for discovery/read flows plus notes, review,
  external-ticket metadata, lifecycle, authoring, message, and hook mutations

Downstream code should not:

- parse description fields directly for review, branch, hook, or message state
- infer lifecycle from raw labels or issue types when `atelier.store` already
  publishes the decision
- construct `bd` argv or depend on `BEADS_DIR`, cwd, Dolt layout, or subprocess
  capability probing from planner/worker/publish policy modules

Direct `atelier.lib.beads` usage remains appropriate only in boundary adapters
that own transport, startup diagnostics, provider API calls, or other
Beads-client-specific concerns.

Downstream migrations should treat the following as still deferred:

- planner, worker, and publish orchestration rewrites that replace legacy
  Beads-shaped call sites with `AtelierStore`
- dependency add/remove parity in the in-memory backend before those mutations
  can move into the shared dual-backend proof suite
- any new store semantic not already published through `atelier.store`

## Known Contract Gaps

- dependency add/remove is not yet proven in the shared dual-backend suite
  because `InMemoryBeadsClient` still treats dependency mutation as outside Tier
  0 scope
- dependency mutation remains covered through explicit process-backed store
  tests until the in-memory backend grows the same semantic support
- if downstream migrations need new store semantics, add them to `atelier.store`
  first and extend both backend suites before moving business logic onto the new
  field or operation

## Deferred Work

This proof slice leaves only the following work deferred:

- planner migrations onto `atelier.store`; that remains deferred to
  [GitHub issue #582]
- publish/orchestration migrations onto `atelier.store` beyond the store-backed
  review, integration-proof, and external-ticket persistence seams; that remains
  deferred to [GitHub issue #584]
- dependency add/remove parity in the in-memory backend so those mutations can
  graduate from process-backed-only coverage into the shared proof suite

Worker lifecycle migrations now follow the [Worker Store Migration Contract].
Publish persistence migrations now follow the
[Publish Store Migration Contract]. Remaining worker-side deferred work stays on
publish/orchestration work above the integration-proof persistence seam plus
richer worktree and epic-close store semantics.

The core store contract, discovery methods, mutation methods, and dual-backend
proof are no longer deferred work. Downstream epics should build on that landed
surface instead of re-deriving store semantics from Beads issue payloads.

<!-- inline reference link definitions. please keep alphabetized -->

[github issue #582]: https://github.com/shaug/atelier/issues/582
[github issue #584]: https://github.com/shaug/atelier/issues/584
[publish store migration contract]: ./publish-store-migration-contract.md
[worker store migration contract]: ./worker-store-migration-contract.md
