---
name: beads
description: >-
  Work with Beads via the bd CLI. Use when a user asks to inspect, plan, or
  synchronize Beads issues (epics/changesets), or to fetch ready work, show
  issue details, or prime agent context.
---

# Beads operations

## Inputs

- beads_dir: optional path to the Beads store (defaults to repo .beads).
- epic_id: Beads epic id to focus on.
- issue_id: specific Beads issue id to show or update.
- labels: optional labels to filter list/ready views.

## Steps

1. Confirm `bd` is available. If a non-repo store is required, set `BEADS_DIR`.
1. Prime Beads context at session start or before compaction:
   - `bd prime`
1. List epics when a user needs to choose work:
   - `bd list --label at:epic --status open`
1. Find ready changesets for an epic:
   - `bd ready --parent <epic-id> --label at:changeset`
1. Show issue details when needed:
   - `bd show <issue-id>`
1. Sync Beads after changes or before ending a session:
   - `bd sync`

## Notes

- Beads is the source of truth for intent and sequencing. Atelier-specific
  execution metadata belongs in workspace config, not in Beads.
- Use labels and description fields according to
  [references/beads-conventions.md](references/beads-conventions.md).
