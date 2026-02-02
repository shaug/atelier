---
name: claim_epic
description: >-
  Claim an epic bead for the current agent, mark it hooked, and store the hook
  on the agent bead.
---

# Claim epic

## Inputs

- epic_id: Bead id of the epic to claim.
- agent_id: Stable identity string (e.g. atelier/worker/alice).
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path (defaults to repo .beads).

## Steps

1. Claim the epic:
   - `bd update <epic_id> --assignee <agent_id> --status in_progress --add-label at:hooked`
2. Load the agent bead description:
   - `bd show <agent_bead_id>`
3. Update `hook_bead` in the agent bead description:
   - Write a new description with `hook_bead: <epic_id>` (use `--body-file`).

## Verification

- Epic shows assignee and `at:hooked` label.
- Agent bead description includes `hook_bead: <epic_id>`.
