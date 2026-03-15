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
1. See [Planner Store Migration Contract] for the current planner-side message
   boundary and deferred gaps.

## Verification

- Message is no longer returned by unread-only store queries.

<!-- inline reference link definitions. please keep alphabetized -->

[planner store migration contract]: ../../../../docs/planner-store-migration-contract.md
