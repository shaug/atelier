# Atelier Dogfood Golden Path

This document describes the minimal, end-to-end flow to dogfood Atelier using
planner and worker modes with human-sized changesets.

## Goal

Validate that the planner and worker can operate concurrently using beads as the
source of truth and that changesets remain reviewable.

## Preconditions

- Project is initialized with `atelier init`.
- Project-scoped beads store exists and uses prefix `at`.
- Planner and worker AGENTS templates are wired into sessions.

## Golden Path (Minimal)

1. Start planner session.
1. Planner checks messages first and reports any worker requests.
1. Planner creates a draft epic with acceptance criteria and intent.
1. Planner keeps the epic as the executable changeset when scope fits, or
   creates child changesets only when decomposition is required.
1. Planner requests approval to promote the epic from `draft` to `ready`.
1. Worker session starts on the approved epic.
1. Worker implements a single changeset and runs required checks.
1. Worker publishes/persists the changeset and updates bead metadata.
1. Worker exits after updating bead status.
1. Planner sees updated status and either:
   - resolves blockers/questions and lets dependency-unblocked ready changesets
     flow to workers, or
   - promotes the next changeset when additional planning decisions are needed,
     or
   - closes the epic when all changesets are complete.

## Self-Updating Worker Supervisor

For Atelier-on-Atelier development, use
`scripts/self_update_worker_supervisor.py` to run one-shot worker cycles while
refreshing the local checkout between cycles.

Example:

```sh
scripts/self_update_worker_supervisor.py \
  --repo-path ~/code/atelier \
  --install-command "just install-editable" \
  -- --mode auto
```

Defaults:

- update policy is fast-forward-only (`--update-policy ff-only`)
- worker command runs once (`atelier work --run-mode once`)
- dry-run mode (`--dry-run`) prints planned update/install/worker actions

## Expected Outcomes

- Beads contain full intent, constraints, and acceptance criteria.
- Changesets stay human-sized unless explicitly approved.
- One-child decomposition is avoided unless rationale is explicitly recorded.
- Worker never expands scope; ambiguities are surfaced via messages.
- Planner does not auto-promote epics without user approval.

## Failure Signals

- Planner or worker runs without seeded AGENTS template.
- Worker prompts for new work or attempts to pick a new epic.
- Changesets exceed guardrails without recorded approval.
- Missing message loop between worker and planner.
