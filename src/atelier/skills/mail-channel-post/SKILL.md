---
name: mail-channel-post
description: >-
  Post a message bead to a shared channel by creating a message with channel
  metadata and optional thread linkage.
---

# Post a channel message

## Inputs

- subject: Subject/title for the message bead.
- body: Message body (markdown).
- channel: Channel name.
- thread: Optional thread id (e.g., epic or changeset bead id).
- beads_dir: Optional Beads store path.

## Steps

1. Render YAML frontmatter with:
   - `channel: <channel>`
   - `thread: <thread>` (if provided)
   - `from: <agent-id>` (use ATELIER_AGENT_ID if available)
1. Create the message bead:
   - `bd create --type task --label at:message --label at:unread --title <subject> --body-file <path>`
1. Do not set an assignee for channel posts.

## Verification

- A new message bead exists with `channel` metadata and the provided body.
