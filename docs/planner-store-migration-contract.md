# Planner Store Migration Contract

Planner startup, discovery, message, and authoring flows now depend on
`atelier.store` as the planner-side issue-store boundary.

This document narrows that statement to the planner runtime. It explains which
planner entry points are proven against `AtelierStore`, which compatibility
seams are still adapter-local, and which follow-on gaps remain deferred for
later epics.

## Proven Planner Boundary

Planner code can treat the following paths as store-backed today:

- startup and discovery reads in `planner_startup_check` and `planner_overview`
- planner authoring in `plan-create-epic` and `plan-changesets`
- planner message reads and mutations in `mail-inbox`, `mail-send`,
  `mail-queue-claim`, and `mail-mark-read`
- planner promotion lifecycle mutations in `plan-promote-epic`

Those flows should depend on `AtelierStore` plus the typed request/query models
it publishes:

- `EpicQuery`, `ChangesetQuery`, and `MessageQuery` for planner reads
- `CreateEpicRequest` and `CreateChangesetRequest` for planner authoring
- `CreateMessageRequest`, `ClaimMessageRequest`, and `MarkMessageReadRequest`
  for planner message handling
- `LifecycleTransitionRequest` for promotion from `deferred` to `open`

Planner modules should not compose raw `bd` argv for those business flows. Raw
Beads usage is still appropriate for transport diagnostics, startup recovery,
and compatibility-only projections that are intentionally outside the published
store surface.

## Planner Compatibility Seams

Two planner-visible compatibility seams remain intentional for now:

- startup and mailbox flows may call the adapter-local
  `_list_startup_messages()` projection when it is available so planner startup
  can still surface legacy assignee-routed messages during migration. That
  projection is startup-only compatibility state, not part of `atelier.store`.
- `mail-send` still writes an assignee recipient hint after creating the durable
  work-threaded message. That assignee value is a compatibility hint for current
  runtime discovery. The durable planner contract is still the thread id, thread
  kind, audience, blocking flag, and reply linkage persisted through
  `CreateMessageRequest`.

Planner logic should rely on the store-level message contract first and treat
compatibility hints as best-effort adapter state only.

## Newly Exposed Planner Gap

`plan-promote-epic` now uses `atelier.store` for the lifecycle mutation and for
child changeset discovery, but its preview still expands raw issue detail
through the Beads client.

That preview gap is explicit rather than accidental: the current store models do
not yet publish the full planner authoring-contract text needed for the
promotion preview, including the rendered description, notes, acceptance
criteria, dependencies, and related-context references exactly as planners
review them before promotion.

Until a richer planner preview model lands in `atelier.store`, keep the preview
read path adapter-local and do not treat it as a reason to bypass the store for
other planner mutations.

## Deferred Work

This planner migration slice leaves the following work deferred:

- worker lifecycle and finalization migrations onto `atelier.store`
- publish and integration orchestration migrations onto `atelier.store`
- a richer planner preview read model in `atelier.store` so `plan-promote-epic`
  can drop its raw issue reads
- shared dual-backend proof for dependency add/remove once the in-memory Beads
  backend supports those mutations at planner parity

No new planner business flow should introduce a fresh Beads-shaped contract. If
a planner path needs more state than `atelier.store` currently exposes, add that
store semantic first and extend the shared parity proof before moving the
planner logic onto it.

## Proof Surface

Representative planner parity is covered by deterministic tests that exercise
planner-facing entry points over both supported Beads backends:

- startup and discovery snapshots through `planner_startup_check` and
  `planner_overview`
- planner authoring through `plan-create-epic` and `plan-changesets`
- planner message flows through `mail-send`, `mail-inbox`, `mail-queue-claim`,
  and `mail-mark-read`

Use this document together with the broader [Atelier Store Contract] when
planning future planner, worker, or publish migrations.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier store contract]: ./atelier-store-contract.md
