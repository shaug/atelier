---
name: startup-contract
description: >-
  Enforce the startup contract: check hooks, handle inbox, then claim work.
---

# Startup contract

## Inputs

- agent_id: Stable identity string (e.g. atelier/worker/alice).
- agent_bead_id: Bead id for the agent.
- mode: prompt|auto (defaults to auto for idle startup).
- beads_dir: Optional Beads store path (defaults to repo .beads).
- queue: Optional message queue name to check when idle.

## Steps

1. Check the current hook:
   - Use `hook-status` (or `bd show <agent_bead_id>`) to read `hook_bead`.
1. If `hook_bead` is present:
   - Verify the epic exists and is still assigned to `agent_id`.
   - Resume work on that epic (do not claim a new one).
1. If no hook is present:
   - Check inbox/queue (message beads) and handle any messages; stop if a
     message requires action before claiming new work.
1. If still idle:
   - List eligible epics (`bd list --label at:epic`). `at:epic` is required
     identity/index metadata for epic discovery.
   - Keep only executable top-level work with status `open`/`in_progress` after
     status+graph evaluation.
   - Do not treat `at:changeset`, `at:ready`, or `cs:*` labels as execution
     gates.
   - In auto mode: pick the oldest ready epic; if none, pick the oldest
     unfinished epic already assigned to `agent_id`.
   - In prompt mode: list eligible epics and ask for an epic id.
1. Claim the selected epic with `claim-epic`, then proceed with work.
1. If no eligible epics exist, send a `NEEDS-DECISION` message to the overseer.

## Verification

- Hook is set for the active epic.
- Messages are marked read when processed.
- Epic eligibility decisions remain status+graph based after `at:epic` indexed
  discovery.
