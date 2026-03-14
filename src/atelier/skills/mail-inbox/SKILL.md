---
name: mail-inbox
description: >-
  List compatibility-routed message beads assigned to the current agent,
  optionally filtering to unread messages.
---

# Mail inbox

## Inputs

- agent_id: Agent identity to filter by assignee.
- unread_only: Whether to filter by `at:unread` (default true).
- beads_dir: Optional Beads store path.

## Steps

1. Use the inbox script:
   - `python3 skills/mail-inbox/scripts/list_inbox.py --agent-id "<agent_id>" [--all] [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. The script reads through `atelier.store` message models and filters by the
   agent runtime role.
1. Treat assignee-based inbox delivery as compatibility-only routing:
   - durable work decisions should also be attached to an epic or changeset
     thread
   - startup/finalize flows may surface threaded blocking messages even without
     a matching assignee

## Verification

- Returned list includes only store-backed threaded messages for the agent
  runtime role.
