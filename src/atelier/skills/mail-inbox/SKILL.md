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

1. List messages assigned to the agent:
   - `bd list --label at:message --assignee <agent_id> [--label at:unread]`
1. Parse frontmatter from each message description if needed.
1. Treat assignee-based inbox delivery as compatibility-only routing:
   - durable work decisions should also be attached to an epic or changeset
     thread
   - startup/finalize flows may surface threaded blocking messages even without
     a matching assignee

## Verification

- Returned list includes only message beads for the agent.
