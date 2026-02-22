---
name: mail-queue-claim
description: >-
  Claim a queued message bead by setting claimed_by/claimed_at in frontmatter.
  Use when an agent pulls work from a shared queue.
---

# Claim a queued message

## Inputs

- message_id: Bead id of the queued message.
- queue: Optional queue name to verify before claiming.
- claimed_by: Optional explicit claimant (defaults to
  ATELIER_AGENT_ID/BD_ACTOR).
- beads_dir: Optional Beads store path.

## Steps

1. Show the message bead:
   - `bd show <message_id>`
1. Parse YAML frontmatter and verify `queue` matches (if provided).
1. If `claimed_by` is already set, stop and report the current claimant.
1. Set:
   - `claimed_by: <agent-id>`
   - `claimed_at: <rfc3339>`
1. Write the updated description with
   `bd update <message_id> --body-file <path>`.

## Verification

- The message frontmatter includes `claimed_by` and `claimed_at`.
