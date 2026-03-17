# Legacy `atelier.beads` inventory

This document records the remaining direct `atelier.beads` usage that is
intentionally retained while the legacy facade is drained. The checked-in
[machine-readable inventory] is the regression boundary used by the test suite.

## Concern domains

- `read-discovery-and-metadata-shims` Keeps the remaining metadata parsing,
  startup, and read-only discovery callers visible for the `at-rhxbc.2` drain
  slice.
- `mutation-and-coordination-shims` Captures close/repair/GC/worktree
  coordination callers that feed the `at-rhxbc.3` drain slice.
- `retained-facade-contract-tests` Marks the facade-only harness and contract
  coverage that should shrink only after the real callers are drained in
  `at-rhxbc.4`.

## Follow-on drain map

- `at-rhxbc.2` Migrate the read/discovery/startup and description-field parsing
  callers listed in the inventory.
- `at-rhxbc.3` Migrate the mutation, GC, and worktree coordination callers
  listed in the inventory.
- `at-rhxbc.4` Remove the remaining facade-only harness and compatibility tests
  by shrinking the allowlist to zero or to an explicitly documented retained
  shim.

<!-- inline reference link definitions. please keep alphabetized -->

[machine-readable inventory]: ./beads-facade-inventory.json
