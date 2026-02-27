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

1. Verify all work nodes for an epic are complete:
   - `bd list --parent <epic_id>`
   - Ensure every changeset has terminal status (`closed`) with terminal PR
     signal (`merged` or `closed`).
1. Close any non-epic parent work nodes if its children are complete.
1. Close the epic and clear the hook through the deterministic helper:
   - `python src/atelier/skills/work-done/scripts/close_epic.py --epic-id <epic_id> --agent-bead-id <agent_bead_id>`
1. For explicit direct-close flows (skip readiness checks), use:
   - `python src/atelier/skills/work-done/scripts/close_epic.py --epic-id <epic_id> --agent-bead-id <agent_bead_id> --direct-close`

## Verification

- Epic is closed.
- Agent hook slot is empty.
- If `external_tickets` has exported GitHub links, close-state metadata is
  reconciled.
