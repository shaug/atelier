# Publish Store Migration Contract

Review-state, integration-proof, and external-ticket metadata persistence used
by publish-adjacent flows now depends on `atelier.store` as the durable
boundary.

This document narrows that statement to review, finalize, and publish-adjacent
paths. It explains which entry points are proven against `AtelierStore`, which
compatibility seams remain adapter- or provider-local, and which follow-on gaps
stay deferred for later epics.

## Proven Publish Boundary

Publish-adjacent code can treat the following persistence paths as store-backed
today:

- review metadata mutations in `changeset-review`,
  `beads.update_changeset_review()`,
  `worker.store_adapter.update_changeset_review()`, `reconcile`, and finalize
  paths that refresh `pr_url`, `pr_number`, `pr_state`, or `review_owner`
- integration-proof persistence in `integration`, `finalize`,
  `finalize_pipeline`, `reconcile`, and `work_finalization_state` through
  store-backed `changeset.integrated_sha` updates
- external ticket metadata persistence in `beads.update_external_tickets()`,
  auto-export, and provider sync/close follow-up paths once provider reads or
  writes complete
- PR ticket rendering in `worker.publish` can rely on the persisted
  `external_tickets` metadata produced by the store-backed update path

Those flows should depend on `AtelierStore` plus the typed models and requests
it publishes:

- `ReviewMetadata` and `UpdateReviewRequest`
- `ExternalTicketLink` and `UpdateExternalTicketsRequest`

Publish/finalize code should not rewrite review fields,
`changeset.integrated_sha`, or `external_tickets` by composing raw Beads
description edits when the store already publishes those semantics.

Future local review mode remains compatible with this shape. Durable review and
integration metadata is store-owned, while provider-specific PR operations stay
outside the contract and can be swapped or skipped without changing the stored
state model.

## Publish Compatibility Seams

Four publish-visible compatibility seams remain intentional for now:

- publish plan resolution still depends on project config plus git state rather
  than a store-owned publish semantic
- branch and worktree mutations still go through git plus worker compatibility
  helpers because `atelier.store` does not yet publish branch/worktree mutation
  operations
- GitHub PR creation, PR updates, and inline review-thread mutations remain
  provider-owned through `github-prs` and `gh`
- PR drafting still reads diff summaries and compatibility issue payload text to
  produce user-facing markdown; `atelier.store` does not yet publish a richer
  PR-authoring model

Publish logic should rely on store-backed review and ticket persistence first
and treat those seams as explicit exceptions rather than alternate persistence
APIs.

## Newly Exposed Publish Gap

The `publish` skill still coordinates branch rebases, pushes, PR creation, and
merge/integration decisions as an orchestration workflow rather than a single
store-owned operation.

That gap is explicit rather than accidental: the current store models publish
durable review, integration-proof, and external-ticket metadata, but not a
composite "publish or persist this changeset" semantic that can evaluate project
config, mutate git refs, and reconcile provider PR state in one typed request.

Until that richer publish semantic lands in `atelier.store`, keep orchestration
in the skill/runtime layer and do not treat it as a reason to bypass the store
for review, integration-proof, or external-ticket persistence.

## Deferred Work

This publish migration slice leaves the following work deferred:

- a store-owned publish/persist orchestration semantic that can combine config,
  git, and provider decisions
- store-owned branch/worktree metadata mutations for publish setup and lineage
  repair
- provider refresh/reconciliation after remote merges, closures, or review state
  drift
- a richer PR-authoring read model in `atelier.store` so publish and PR-draft
  flows can drop compatibility issue payload reads

No new publish or review business flow should introduce a fresh Beads-shaped
metadata write. If a publish path needs more durable state than `atelier.store`
currently exposes, add that store semantic first and extend the shared parity
proof before moving the workflow onto it.

## Proof Surface

Representative publish/review parity is covered by deterministic tests that
exercise review, integration-proof, and external-ticket persistence across both
supported Beads backends:

- review-state and reviewer-owner persistence through store-backed update
  operations
- integration-proof persistence through the worker store adapter used by
  finalize and publish-adjacent paths
- external-ticket metadata round-trips plus PR ticket rendering from the stored
  metadata that publish/PR-draft paths consume

Use this document together with the broader [Atelier Store Contract] when
planning future publish, review, or provider-boundary migrations.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier store contract]: ./atelier-store-contract.md
