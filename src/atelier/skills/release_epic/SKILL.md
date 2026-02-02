---
name: release_epic
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

1. Release the epic:
   - `bd update <epic_id> --assignee "" --status open --remove-label at:hooked`
2. Load the agent bead description:
   - `bd show <agent_bead_id>`
3. Clear the hook in the agent bead description:
   - Write a new description with `hook_bead: null` (use `--body-file`).

## Verification

- Epic has no assignee and no `at:hooked` label.
- Agent bead description includes `hook_bead: null`.
