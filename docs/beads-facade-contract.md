# `atelier.beads` Retirement Contract

This document publishes the retained public `atelier.beads` surface after the
post-store drain work. The machine-readable [contract file] is the regression
boundary that blocks new public facade growth.

## Contract rules

- The checked-in contract tracks the full top-level public namespace exposed by
  `src/atelier/beads.py`, including names introduced by imports or assignments.
  That makes accidental facade regrowth visible even when it does not come from
  a new `def` or `class`.
- `src/atelier/beads.py` keeps only the public functions and classes listed in
  the retained-surface section of the checked-in contract.
- New top-level public symbols in `atelier.beads` are not allowed unless the
  retirement contract is intentionally updated in the same change.
- Result models that now belong to newer abstractions stay owned there:
  `atelier.store` owns external-ticket and epic-discovery result shapes, and
  `atelier.lib.beads` owns event-history overflow repair results.
- Helper-only paths that remain inside `src/atelier/beads.py` must stay private
  so the facade cannot regrow by accident through test-only conveniences.

## Retired symbols in this slice

- `IssuePrefixRenamePreview`, `ExternalTicketMetadataGap`, and `run_bd_issues`
  were internal helpers that no longer needed public module visibility.
- `ensure_custom_types`, `external_label`, `policy_role_label`, and
  `list_epics_by_workspace_label` were dead public helpers with only internal
  call sites.
- `EventHistoryOverflowRepairResult`, `ExternalTicketMetadataRepairResult`,
  `ExternalTicketReconcileResult`, `EpicIdentityViolation`, and
  `EpicDiscoveryParityReport` were duplicate model definitions that are now
  owned by `atelier.lib.beads` or `atelier.store`.

## Remaining shim boundary

- Runtime callers still use `atelier.beads` as a compatibility facade for
  startup/bootstrap, issue discovery, metadata reads/writes, lifecycle shims,
  and targeted repair flows.
- The remaining surface is intentionally grouped into the four concern domains
  recorded in the machine-readable contract so future drain work can shrink
  domains without rediscovering the whole module boundary.

<!-- inline reference link definitions. please keep alphabetized -->

[contract file]: ./beads-facade-contract.json
