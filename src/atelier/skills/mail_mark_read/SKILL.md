---
name: mail_mark_read
description: >-
  Mark a message bead as read by removing the unread label.
---

# Mail mark read

## Inputs

- message_id: Bead id of the message to mark read.
- beads_dir: Optional Beads store path.

## Steps

1. Remove the unread label:
   - `bd update <message_id> --remove-label at:unread`

## Verification

- Message bead no longer has the `at:unread` label.
