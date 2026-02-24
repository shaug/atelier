---
name: tickets
description: >-
  Orchestrate external ticket import, export, link, and sync operations using
  provider skills plus Beads updates. Use when a user asks to import tickets
  into planning, export beads to a provider, link existing tickets, or refresh
  ticket state.
---

# Manage external ticket references

## Inputs

- operation: `import` | `export` | `link` | `sync_state`.
- issue_id: Bead id to update (epic or changeset).
- ticket_refs: One or more external ticket IDs or URLs to attach (for link).
- provider: Provider name (`github`, `linear`, `jira`, `beads`, etc).
- relation: Optional relation (primary/secondary/context/derived).
- direction: Optional direction (imported/exported/linked).
- sync_mode: Optional sync mode (manual/import/export/sync).
- include_state: Optional boolean for state sync (`sync_state` op).
- include_body: Optional boolean for body/content sync (`sync_state` op).
- include_notes: Optional boolean for notes/summary sync (`sync_state` op).
- beads_dir: Optional Beads store path.

## Steps

1. Determine provider context:
   - Use `ATELIER_EXTERNAL_PROVIDERS` and `ATELIER_GITHUB_REPO` when present.
   - If the provider is not configured, ask the overseer before proceeding.
1. Show the target bead:
   - `bd show <issue_id>`
1. Route based on `operation`:
   - `import`: use the provider skill to list or read candidate tickets. Create
     local beads as needed (epics or context) and attach refs via
     `external-import` with `direction=imported`.
   - `export`: use the provider skill to create tickets from the bead content.
     Attach refs via `external-import` with `direction=exported`.
   - `link`: attach existing tickets via `external-import` with
     `direction=linked` (and optional `relation`/`sync_mode`).
   - `sync_state`: refresh cached state via `external-sync` (pass optional
     include_state/include_body/include_notes toggles).
1. When provider operations are required:
   - GitHub Issues: use `github` → `github-issues` for create/read/update.
   - Other systems: use their provider skill (linear/jira/etc).
1. Verify Beads metadata:
   - `external_tickets` includes provider/id/url plus
     relation/direction/sync_mode.
   - Provider labels (e.g., `ext:github`) match attached refs.
1. For retrying non-fatal auto-export errors from planning scripts, use:
   - `python skills/tickets/scripts/auto_export_issue.py --issue-id <issue_id>`
1. For Beads issues with `ext:<provider>` labels but missing `external_tickets`,
   run deterministic metadata repair:
   - `python skills/tickets/scripts/repair_external_ticket_metadata.py`
   - add `--apply` to write recovered metadata.

## Verification

- The bead description includes an `external_tickets` field.
- Provider labels match the attached ticket refs.
- Direction/relation/sync_mode are set for any new associations.
- For repaired issues, metadata was recovered from Beads event history and
  `external_tickets` is present again.
