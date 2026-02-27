---
name: changeset-signals
description: >-
  Read derived PR lifecycle signals for a changeset and outline the next steps.
  Use when a worker needs guidance on review state, approvals, or outstanding
  actions for a changeset.
---

# Changeset lifecycle signals

## Inputs

- epic_id: Bead id for the epic (optional; used to filter results).
- changeset_id: Bead id for the changeset (optional; used to focus output).

## Steps

1. Fetch status with PR-derived signals:
   - `atelier status --format=json`
1. Locate the epic and changeset in `changeset_details`:
   - Match by `id` (changeset id) or by branch if needed.
1. Read derived fields:
   - `lifecycle_state` (`pushed`, `draft-pr`, `pr-open`, `in-review`,
     `approved`, `merged`, `closed`)
   - `review_requested` (boolean)
   - `pushed` (boolean)
   - `pr` metadata (number, url, state, is_draft, review_decision, mergeable,
     merge_state_status)
1. Provide next-step guidance:
   - `pushed`: open a PR.
   - `draft-pr`: move to ready-for-review and request reviewer.
   - `pr-open` with no reviewer: request a reviewer.
   - `in-review`: address comments and update the branch.
   - `approved`: confirm with overseer before merge.
   - `merge_state_status=DIRTY` (or equivalent conflict signal): rebase/merge
     default branch, resolve conflicts, push, then refresh signals.
   - `merged`: close the changeset bead.
   - `closed`: mark the changeset as abandoned by setting terminal status/PR
     metadata (`status=closed`, `pr_state=closed`).

## Verification

- Output identifies the lifecycle state and recommended next action.
