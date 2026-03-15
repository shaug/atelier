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

1. Run the queue-claim script:
   - `python3 skills/mail-queue-claim/scripts/claim_message.py <message_id> [--queue "<queue>"] [--claimed-by "<agent_id>"] [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. The script validates queue identity, enforces claim ownership, and persists
   claim metadata through `atelier.store`.
1. See [Worker Store Migration Contract] for the worker-side queue boundary and
   deferred gaps.

## Verification

- The claimed message includes `claimed_by` and `claimed_at`, and later unread
  queue reads show it as claimed.

<!-- inline reference link definitions. please keep alphabetized -->

[worker store migration contract]: ../../../../docs/worker-store-migration-contract.md
