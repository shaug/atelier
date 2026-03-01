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
   - `at:epic` is required identity/index metadata for epic discovery.
1. Find ready work for an epic:
   - `bd ready --parent <epic-id>` returns ready work beads.
   - Changesets are beads without children (leaf nodes). Filter or query
     children to identify which ready beads are changesets vs. parent work
     beads.
1. Show issue details when needed:
   - `bd show <issue-id>`
1. When creating new issues, prefer explicit fields:
   - `bd create --acceptance ... --design ... --estimate ... --priority ...`
   - use `--notes` / `--append-notes` for addendums without rewriting
     descriptions
1. Persist Beads changes only when a Dolt working-set commit is required:
   - Check backend/capability first: `bd dolt show --json`.
   - Check mode and pending state: `bd config get dolt.auto-commit --json` and
     `bd vc status --json`.
   - Run `bd dolt commit` only when auto-commit mode is `batch` and pending
     working-set changes exist.
   - In direct/auto-persist modes (for example `off`/`on`) or when no pending
     changes exist, skip `bd dolt commit`.

## Notes

- Beads is the source of truth for intent and sequencing. Execution metadata
  should live in Atelier's project store and be derived from git/PR state rather
  than custom Beads schema.
- Lifecycle authority is canonical status + graph shape. `cs:*` lifecycle labels
  are not execution gates.
- Use labels and description fields according to
  [references/beads-conventions.md](references/beads-conventions.md).
