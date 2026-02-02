---
name: hook_status
description: >-
  Inspect the agent bead to determine the currently hooked epic.
---

# Hook status

## Inputs

- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path.

## Steps

1. Show the agent bead:
   - `bd show <agent_bead_id>`
2. Read the `hook_bead` field from the description.

## Verification

- Report the current `hook_bead` value (or `null` if none).
