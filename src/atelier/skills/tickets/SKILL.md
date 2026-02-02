---
name: tickets
description: >-
  Attach or update external ticket references on Beads issues (epics or
  changesets). Use when a user asks to link external tickets, list existing
  refs, or update their state.
---

# Manage external ticket references

## Inputs

- issue_id: Bead id to update (epic or changeset).
- ticket_refs: One or more external ticket IDs or URLs to attach.
- provider: Optional provider name (github, linear, jira, etc).
- beads_dir: Optional Beads store path.

## Steps

1. Show the target bead:
   - `bd show <issue_id>`
1. Parse existing `external_tickets` from the description (JSON list).
1. Merge in the new ticket refs, normalizing to:
   - `provider`, `id`, optional `url`, `state`, `on_close`.
1. Update the description with the new `external_tickets` JSON payload using
   `bd update <issue_id> --body-file <path>`.
1. Add provider labels (e.g., `ext:github`) and remove stale ones.

## Verification

- The bead description includes an `external_tickets` field.
- Provider labels match the attached ticket refs.
