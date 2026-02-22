---
name: mail-send
description: >-
  Send a message bead to an agent by creating a message issue with YAML
  frontmatter and assigning it to the recipient.
---

# Mail send

## Inputs

- subject: Message subject line.
- body: Message body content.
- to: Recipient agent id (assignee).
- from: Sender agent id.
- thread: Optional thread id (bead id).
- reply_to: Optional message id being replied to.
- beads_dir: Optional Beads store path.

## Steps

1. Render the message description with YAML frontmatter (use
   `atelier.messages.render_message`).
1. Create the message bead:
   - `bd create --type task --label at:message --label at:unread --title <subject> --assignee <to> --body-file <path>`

## Verification

- Message bead exists and is assigned to the recipient.
- Description includes YAML frontmatter with `from`, `thread`, and `reply_to`
  when provided.
