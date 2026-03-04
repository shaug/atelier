---
name: planner-startup-check
description: >-
  Run the planner startup message loop: review inbox and queues, summarize
  decisions, and create or update beads before planning continues.
---

# Planner startup check

Create or update deferred beads immediately when you identify actionable issues
during startup triage. Do not wait for approval to capture deferred work.

## Inputs

- agent_id: Planner agent identity.
- beads_dir: Optional explicit Beads store override. Default is the
  project-scoped Beads root.
- repo_dir: Optional explicit repo root override. Defaults to `./worktree` then
  cwd.
- queue: Optional queue name to check (if queues are enabled).

## Steps

1. List unread inbox messages for the planner.
1. List queued messages (if queues are enabled) and offer to claim them.
1. Summarize each message and extract actionable issues.
1. Create or update deferred beads immediately for actionable issues.
1. Capture required decisions from the overseer only when a real blocker exists
   (for example, promotion from deferred to open).
1. Mark messages as read when addressed.
1. Run `epic-list` with drafts enabled and include its output verbatim in the
   startup response:
   - `python3 skills/epic-list/scripts/list_epics.py --show-drafts`
   - Do not reformat, summarize, or compress the list.
   - Epic discovery is indexed by the required `at:epic` label. Missing
     `at:epic` means the issue is outside the planner epic pool.
   - When startup diagnostics report active top-level work missing executable
     identity, apply deterministic remediation:
     `bd update <id> --type epic --add-label at:epic`
   - `cs:*` lifecycle labels are not execution gates.

## Canonical startup command plan

Planner startup triage uses a fixed ordered command plan with explicit I/O:

1. `list_inbox_unread_messages`
   - inputs: `agent_id`
   - output: `inbox_messages`
1. `list_queue_unread_messages`
   - inputs: none
   - output: `queued_messages`
1. `list_indexed_epics`
   - inputs: none
   - output: `epics`
1. `compute_epic_discovery_parity`
   - inputs: `epics`
   - output: `parity_report`

All Beads invocations in this flow run through the shared startup helper and
reject unsupported invocation forms.

## Verification

- Inbox and queue are processed before planning work starts.
- Actionable issues are captured as deferred work without waiting for approval.
- Messages are summarized with explicit decisions or follow-up beads.
- Active epic listing (draft/open/in-progress/blocked as available) is included
  in stable `epic-list` format.
- Startup triage treats canonical status + dependency graph as lifecycle
  authority after `at:epic` indexed discovery.

## On-demand refresh

- During an active planner session, re-run the same read-only overview with:
  `python3 skills/planner-startup-check/scripts/refresh_overview.py --agent-id "$ATELIER_AGENT_ID" --repo-dir ./worktree`
- This refresh is read-only and includes:
  - unread planner inbox messages
  - queued messages with queue name and claim state
  - active epics in stable `epic-list --show-drafts` format
  - Beads root + total epic count diagnostics for planner/worker parity checks

## Parity and recovery

- Use the one-shot parity check and recovery playbook in
  `docs/beads-store-parity.md`.
- For direct Beads diagnostics, use only supported raw forms:
  `BEADS_DIR="<beads-root>" bd ...` or `bd --db "<beads-root>/beads.db" ...`.
