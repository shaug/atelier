---
name: epic-claim
description: >-
  Claim a specified epic bead for the current agent.
---

# Epic claim

## Inputs

- epic_id: Bead id of the epic to claim.
- agent_id: Stable identity string (e.g. atelier/worker/alice).
- agent_bead_id: Bead id for the agent.
- beads_dir: Optional Beads store path (defaults to repo .beads).

## Steps

1. Run `claim-epic` with the provided inputs.
1. Verify the epic is assigned and hooked to `agent_id`.
1. Verify the agent bead `hook_bead` points at `epic_id`.

## Verification

- Epic shows assignee and `at:hooked` label.
- Agent bead description includes `hook_bead: <epic_id>`.
