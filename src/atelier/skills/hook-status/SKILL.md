---
name: hook-status
description: >-
  Inspect the agent bead to determine the currently hooked epic.
---

# Hook status

## Inputs

- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path.

## Steps

1. Run the hook-status script:
   - `python3 skills/hook-status/scripts/hook_status.py <agent_bead_id> [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. Read the current hook through the `atelier.store` hook model.
1. See [Worker Store Migration Contract] for the store-backed hook boundary.

## Verification

- Report the current `hook_bead` value (or `null` if none).

<!-- inline reference link definitions. please keep alphabetized -->

[worker store migration contract]: ../../../../docs/worker-store-migration-contract.md
