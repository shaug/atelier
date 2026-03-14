# Atelier Store Contract

This document defines the Atelier-owned planning store contract that sits above
`atelier.lib.beads`. It freezes the vocabulary and invariant ownership for
planner and worker logic before the adapter slices land.

## Public Contract

The published Python surface lives in `atelier.store`.

Typed models:

- `EpicRecord`
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
- `ClaimMessageRequest`
- `SetHookRequest`
- `ClearHookRequest`
- `UpdateReviewRequest`
- `LifecycleTransitionRequest`

Async protocol:

- `AtelierStore`

The contract is intentionally backend-neutral. It does not expose `bd` commands,
`BEADS_DIR`, Dolt layout, filesystem probes, transport details, or startup
marker paths.

## Atelier-Owned Invariants

Atelier owns the business semantics below even when the concrete adapter is
backed by Beads:

- Lifecycle status uses the canonical set
  `deferred|open|in_progress|blocked|closed`.
- Review state is tracked separately from lifecycle state using the canonical PR
  lifecycle values `pushed|draft-pr|pr-open|in-review|approved|merged|closed`.
- Changesets may carry branch metadata plus review and integration metadata
  without exposing how the backend persists those fields.
- Dependency satisfaction is an Atelier decision. Adapters may persist raw
  dependency edges, but whether a dependency counts as satisfied is owned by
  Atelier lifecycle policy.
- Message routing is an Atelier contract: `delivery`, `thread_id`,
  `thread_kind`, `audience`, `blocking`, `reply_to`, and queue claim metadata
  are stable store concepts.
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

The store adapter may use those lower-level details internally, but they are not
part of the Atelier store contract.

## Deferred Work

This contract-definition slice does not include the following work:

- concrete graph and discovery adapters from `AtelierStore` to the Beads client;
  that belongs to `at-njpt4.2`
- lifecycle, review, message, hook, and dependency mutation adapters; that
  belongs to `at-njpt4.3`
- dual-backend proof over both the process-backed and in-memory Beads clients;
  that belongs to `at-njpt4.4`
- planner, worker, and publish migrations onto this store surface; that remains
  deferred to the later migration epics

The immediate review goal for this slice is narrower: downstream work should be
able to implement adapters against `atelier.store` without redesigning the core
vocabulary during review.
