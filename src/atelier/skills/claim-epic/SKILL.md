---
name: claim-epic
description: >-
  Claim an epic bead for the current agent, mark it in progress, and store the
  hook on the agent bead.
---

# Claim epic

## Inputs

- epic_id: Bead id of the epic to claim.
- agent_id: Stable identity string (e.g. atelier/worker/alice).
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path (defaults to repo .beads).

## Steps

1. Claim the epic through the worker lifecycle helper:
   - persist assignee, `in_progress`, and `at:hooked` together as one verified
     claim mutation
1. Re-read the epic to verify the assignee is still `<agent_id>` and the hook
   label remains present.
1. Persist the agent hook through the store-owned hook mutation for
   `<agent_bead_id>`.
1. See [Worker Store Migration Contract] for the store-backed claim/hook
   boundary and the remaining compatibility seams.

## Verification

- Epic shows assignee and `at:hooked` label.
- Agent bead hook resolves to `<epic_id>`.

<!-- inline reference link definitions. please keep alphabetized -->

[worker store migration contract]: ../../../../docs/worker-store-migration-contract.md
