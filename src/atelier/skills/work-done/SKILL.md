---
name: work-done
description: >-
  Close an epic and clear the agent hook when work is complete.
---

# Work done

## Inputs

- epic_id: Bead id of the epic to close.
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path.

## Steps

1. Verify all changesets are complete:
   - `bd list --parent <epic_id> --label at:changeset`
   - Ensure every changeset is `cs:merged` or `cs:abandoned`.
1. Close the epic:
   - `bd close <epic_id>`
1. Clear the hook slot on the agent bead:
   - `bd slot clear <agent_bead_id> hook`

## Verification

- Epic is closed.
- Agent hook slot is empty.
