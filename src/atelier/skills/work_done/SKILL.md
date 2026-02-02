---
name: work_done
description: >-
  Close an epic and clear the agent hook when work is complete.
---

# Work done

## Inputs

- epic_id: Bead id of the epic to close.
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path.

## Steps

1. Close the epic:
   - `bd close <epic_id>`
1. Show the agent bead:
   - `bd show <agent_bead_id>`
1. Clear the hook in the agent bead description:
   - Write a new description with `hook_bead: null` (use `--body-file`).

## Verification

- Epic is closed.
- Agent bead description includes `hook_bead: null`.
