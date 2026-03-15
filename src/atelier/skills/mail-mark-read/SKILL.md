---
name: mail-mark-read
description: >-
  Mark a message bead as read by removing the unread label.
---

# Mail mark read

## Inputs

- message_id: Bead id of the message to mark read.
- beads_dir: Optional Beads store path.

## Steps

1. Run the mark-read script:
   - `python3 skills/mail-mark-read/scripts/mark_read.py <message_id> [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. The script verifies the unread transition through `atelier.store`.

## Verification

- Message is no longer returned by unread-only store queries.
