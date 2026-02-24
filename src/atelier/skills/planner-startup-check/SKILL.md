---
name: planner-startup-check
description: >-
  Run the planner startup message loop: review inbox and queues, summarize
  decisions, and create or update beads before planning continues.
---

# Planner startup check

Create or update draft beads immediately when you identify actionable issues
during startup triage. Do not wait for approval to capture drafts.

## Inputs

- agent_id: Planner agent identity.
- beads_dir: Optional Beads store path.
- queue: Optional queue name to check (if queues are enabled).

## Steps

1. List unread inbox messages for the planner.
1. List queued messages (if queues are enabled) and offer to claim them.
1. Summarize each message and extract actionable issues.
1. Create or update draft beads immediately for actionable issues.
1. Capture required decisions from the overseer only when a real blocker exists
   (for example, promotion from draft to ready).
1. Mark messages as read when addressed.
1. Run `epic-list` with drafts enabled and include its output verbatim in the
   startup response:
   - `python3 skills/epic-list/scripts/list_epics.py --show-drafts`
   - Do not reformat, summarize, or compress the list.

## Verification

- Inbox and queue are processed before planning work starts.
- Actionable issues are captured as drafts without waiting for approval.
- Messages are summarized with explicit decisions or follow-up beads.
- Active epic listing (draft/open/in-progress/blocked as available) is included
  in stable `epic-list` format.

## On-demand refresh

- During an active planner session, re-run the same read-only overview with:
  `python3 skills/planner-startup-check/scripts/refresh_overview.py --agent-id "$ATELIER_AGENT_ID"`
- This refresh is read-only and includes:
  - unread planner inbox messages
  - queued messages with queue name and claim state
  - active epics in stable `epic-list --show-drafts` format
