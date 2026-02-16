---
name: planner_startup_check
description: >-
  Run the planner startup message loop: review inbox and queues, summarize
  decisions, and create or update beads before planning continues.
---

# Planner startup check

## Inputs

- agent_id: Planner agent identity.
- beads_dir: Optional Beads store path.
- queue: Optional queue name to check (if queues are enabled).

## Steps

1. List unread inbox messages for the planner.
1. List queued messages (if queues are enabled) and offer to claim them.
1. Summarize each message and capture required decisions from the overseer.
1. Create or update beads based on message content.
1. Mark messages as read when addressed.

## Verification

- Inbox and queue are processed before planning work starts.
- Messages are summarized with explicit decisions or follow-up beads.
