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
   - `bd --no-daemon prime` (default)
1. List epics when a user needs to choose work:
   - `bd --no-daemon list --label at:epic --status open` (default)
1. Find ready changesets for an epic:
   - `bd --no-daemon ready --parent <epic-id> --label at:changeset` (default)
1. Show issue details when needed:
   - `bd --no-daemon show <issue-id>` (default)
1. When creating new issues, prefer explicit fields:
   - `bd --no-daemon create --acceptance ... --design ... --estimate ... --priority ...`
     (default)
   - use `--notes` / `--append-notes` for addendums without rewriting
     descriptions
1. Sync Beads after changes or before ending a session:
   - `bd --no-daemon sync` (default)

## Notes

- Beads is the source of truth for intent and sequencing. Execution metadata
  should live in Atelier's project store and be derived from git/PR state rather
  than custom Beads schema.
- Default to `--no-daemon` for agent workflows.
- Use daemon-backed invocations only when daemon use is explicitly configured
  (project `beads` config, or daemon-specific env overrides such as
  `ATELIER_BD_DAEMON` / `BEADS_DAEMON` / `BEADS_NO_DAEMON`).
- Keep `bd daemon ...` commands for explicit daemon lifecycle management.
- Use labels and description fields according to
  [references/beads-conventions.md](references/beads-conventions.md).
