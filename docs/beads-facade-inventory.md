# Legacy `atelier.beads` inventory

This document records the remaining direct `atelier.beads` usage that is
intentionally retained while the legacy facade is drained. The checked-in
[machine-readable inventory] is the regression boundary used by the test suite.

## Concern domains

- `retained-facade-contract-tests` Marks the facade-only harness and contract
  coverage that should shrink only after the real callers are drained and the
  remaining compatibility contract is explicit.

## Follow-on drain map

- Retirement proof: Remove the remaining facade-only harness and compatibility
  tests by shrinking the allowlist to zero or to an explicitly documented
  retained shim.

<!-- inline reference link definitions. please keep alphabetized -->

[machine-readable inventory]: ./beads-facade-inventory.json
