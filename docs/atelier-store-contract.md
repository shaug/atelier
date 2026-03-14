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
- `CreateMessageRequest`
- `AppendNotesRequest`
- `ClaimMessageRequest`
- `SetHookRequest`
- `ClearHookRequest`
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
- `EpicRecord.root_branch`
- `DependencyRecord.status`
- `MessageRecord.blocking_roles`

## Atelier-Owned Invariants

Atelier owns the business semantics below even when the concrete store
implementation is backed by Beads:

- Lifecycle status uses the canonical set
  `deferred|open|in_progress|blocked|closed`.
- Review state is tracked separately from lifecycle state using the canonical PR
  lifecycle values `pushed|draft-pr|pr-open|in-review|approved|merged|closed`.
- Changesets may carry branch metadata plus review and integration metadata
  without exposing how the backend persists those fields.
- Dependency satisfaction is an Atelier decision. Adapters may persist raw
  dependency edges, but whether a dependency counts as satisfied is owned by
  Atelier lifecycle policy.
- Durable message routing is an Atelier contract: store-level messages are
  `work-threaded` on `epic|changeset` threads, and `thread_id`, `thread_kind`,
  `audience`, `blocking`, `reply_to`, and queue claim metadata are stable store
  concepts. `blocking_roles` is the normalized read-time routing decision used
  by planner and worker startup flows. Assignee-delivery hints remain
  adapter-local compatibility state rather than published store vocabulary.
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
listing and ready discovery, message listing, hook lookup, branch metadata, and
review/dependency state decoding. Representative mutation coverage includes
review updates, note appends, lifecycle transitions, message create/claim, and
agent hook set/clear.

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
- `ReviewMetadata`, `DependencyRecord`, `LifecycleTransition`
- the request/query models in `atelier.store.contract`, including
  `AppendNotesRequest`, `UpdateReviewRequest`, `LifecycleTransitionRequest`,
  `CreateMessageRequest`, `ClaimMessageRequest`, `SetHookRequest`, and
  `ClearHookRequest`
- shared dual-backend parity for discovery/read flows plus notes, review,
  lifecycle, message, and hook mutations

Downstream code should not:

- parse description fields directly for review, branch, hook, or message state
- infer lifecycle from raw labels or issue types when `atelier.store` already
  publishes the decision
- construct `bd` argv or depend on `BEADS_DIR`, cwd, Dolt layout, or subprocess
  capability probing from planner/worker/publish policy modules

Direct `atelier.lib.beads` usage remains appropriate only in boundary adapters
that own transport, startup diagnostics, or other Beads-client-specific
concerns.

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
- worker migrations onto `atelier.store`; that remains deferred to
  [GitHub issue #583]
- publish/integration migrations onto `atelier.store`; that remains deferred to
  [GitHub issue #584]
- dependency add/remove parity in the in-memory backend so those mutations can
  graduate from process-backed-only coverage into the shared proof suite

The core store contract, discovery methods, mutation methods, and dual-backend
proof are no longer deferred work. Downstream epics should build on that landed
surface instead of re-deriving store semantics from Beads issue payloads.

<!-- inline reference link definitions. please keep alphabetized -->

[github issue #582]: https://github.com/shaug/atelier/issues/582
[github issue #583]: https://github.com/shaug/atelier/issues/583
[github issue #584]: https://github.com/shaug/atelier/issues/584
