---
name: heartbeat
description: >-
  Update the agent bead heartbeat timestamp for GC and liveness checks.
---

# Heartbeat

## Inputs

- agent_bead_id: Bead id for the agent.
- timestamp: RFC3339 timestamp (UTC preferred).
- beads_dir: Optional Beads store path.

## Steps

1. Show the agent bead:
   - `bd show <agent_bead_id>`
1. Update the description with `heartbeat_at: <timestamp>` (use `--body-file`).

## Verification

- Agent bead description contains the updated `heartbeat_at` field.
