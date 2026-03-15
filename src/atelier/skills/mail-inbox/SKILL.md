---
name: mail-inbox
description: >-
  List compatibility-routed message beads assigned to the current agent, with
  explicit unread-only and all-messages modes.
---

# Mail inbox

## Inputs

- agent_id: Agent identity to filter by assignee.
- mode: Defaults to unread-only; use `--unread` for an explicit unread-only
  invocation or `--all` to include already-read messages.
- beads_dir: Optional Beads store path.

## Steps

1. Use the inbox script:
   - `python3 skills/mail-inbox/scripts/list_inbox.py --agent-id "<agent_id>" [--unread | --all] [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. The script reads through `atelier.store` message models and filters by the
   agent runtime role.
1. Treat assignee-based inbox delivery as compatibility-only routing:
   - durable work decisions should also be attached to an epic or changeset
     thread
   - startup/finalize flows may surface threaded blocking messages even without
     a matching assignee
1. See [Planner Store Migration Contract] for the current planner-side message
   boundary and deferred gaps.

## Verification

- Default invocations and explicit `--unread` invocations return the unread-only
  threaded messages for the agent runtime role.
- `--all` broadens the result set to include already-read threaded messages for
  the agent runtime role.

<!-- inline reference link definitions. please keep alphabetized -->

[planner store migration contract]: ../../../../docs/planner-store-migration-contract.md
