---
name: mail-inbox
description: >-
  List message beads assigned to the current agent, optionally filtering to
  unread messages.
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

## Verification

- Returned list includes only message beads for the agent.
