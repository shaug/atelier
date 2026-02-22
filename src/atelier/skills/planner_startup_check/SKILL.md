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
1. Run `epic_list` with drafts enabled and include its output verbatim in the
   startup response:
   - `python3 skills/epic_list/scripts/list_epics.py --show-drafts`
   - Do not reformat, summarize, or compress the list.

## Verification

- Inbox and queue are processed before planning work starts.
- Messages are summarized with explicit decisions or follow-up beads.
- Active epic listing (draft/open/in-progress/blocked as available) is included
  in stable `epic_list` format.

## On-demand refresh

- During an active planner session, re-run the same read-only overview with:
  `python3 skills/planner_startup_check/scripts/refresh_overview.py --agent-id "$ATELIER_AGENT_ID"`
- This refresh is read-only and includes:
  - unread planner inbox messages
  - queued messages with queue name and claim state
  - active epics in stable `epic_list --show-drafts` format
