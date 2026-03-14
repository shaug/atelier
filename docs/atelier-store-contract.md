# Atelier Store Contract

This document defines the Atelier-owned planning store contract that sits above
`atelier.lib.beads`. It freezes the vocabulary and invariant ownership for
planner and worker logic before the implementation slices land.

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
  concepts. Assignee-delivery hints remain adapter-local compatibility state
  rather than published store vocabulary.
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

## Deferred Work

This contract-definition slice does not include the following work:

- implementing `AtelierStore` graph and discovery methods on top of the Beads
  client; that belongs to [GitHub issue #644]
- implementing `AtelierStore` lifecycle, notes, review, message, hook, and
  dependency mutation methods on top of the Beads client; that belongs to
  [GitHub issue #645]
- dual-backend proof over both the process-backed and in-memory Beads clients;
  that belongs to [GitHub issue #646]
- planner, worker, and publish migrations onto this store surface; that remains
  deferred to [GitHub issue #582], [GitHub issue #583], and [GitHub issue #584]

The immediate review goal for this slice is narrower: downstream work should be
able to implement `AtelierStore` on top of `atelier.lib.beads.Beads` without
redesigning the core vocabulary during review.

<!-- inline reference link definitions. please keep alphabetized -->

[github issue #582]: https://github.com/shaug/atelier/issues/582
[github issue #583]: https://github.com/shaug/atelier/issues/583
[github issue #584]: https://github.com/shaug/atelier/issues/584
[github issue #644]: https://github.com/shaug/atelier/issues/644
[github issue #645]: https://github.com/shaug/atelier/issues/645
[github issue #646]: https://github.com/shaug/atelier/issues/646
