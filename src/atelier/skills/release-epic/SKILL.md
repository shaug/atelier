---
name: release-epic
description: >-
  Release a claimed epic by clearing the assignee, removing the hooked label,
  and clearing the agent hook.
---

# Release epic

## Inputs

- epic_id: Bead id of the epic to release.
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path.

## Steps

1. Release the epic through the worker lifecycle helper:
   - clear assignee, reset lifecycle to `open` when appropriate, and remove the
     `at:hooked` label with verification
1. Clear the agent hook through the store-owned hook mutation for
   `<agent_bead_id>`.
1. See [Worker Store Migration Contract] for the worker-side release boundary
   and the remaining compatibility seams.

## Verification

- Epic has no assignee and no `at:hooked` label.
- Agent bead hook resolves to `null`.

<!-- inline reference link definitions. please keep alphabetized -->

[worker store migration contract]: ../../../../docs/worker-store-migration-contract.md
