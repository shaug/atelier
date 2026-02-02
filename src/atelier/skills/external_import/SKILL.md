---
name: external_import
description: >-
  Import external ticket references into Beads without pulling full remote
  state. Use when a user wants to attach external tickets to epics/changesets.
---

# Import external ticket references

## Inputs

- issue_id: Bead id to update (epic or changeset).
- provider: External provider name.
- ticket_id: External ticket identifier.
- ticket_url: Optional URL.
- beads_dir: Optional Beads store path.

## Steps

1. Show the bead:
   - `bd show <issue_id>`
1. Add/merge the ticket ref into `external_tickets` in the description.
1. Add the `ext:<provider>` label to the bead.
1. Do not fetch remote metadata unless the user explicitly requests it.

## Verification

- The bead includes the new `external_tickets` entry and provider label.
