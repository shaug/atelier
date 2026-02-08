---
name: external_sync
description: >-
  Synchronize external ticket state for Beads issues when explicitly requested.
  Use when a user wants to refresh state or mirror changes.
---

# Sync external ticket state

## Inputs

- issue_id: Bead id to sync (epic or changeset).
- provider: Provider name to sync (optional; sync all if omitted).
- beads_dir: Optional Beads store path.

## Steps

1. Show the bead and parse `external_tickets` entries.
1. For each entry, optionally call provider-specific tooling (e.g., GitHub or
   Linear skills) to fetch current state if the user asks for it.
1. Update the `state` and `state_updated_at` values in `external_tickets` based
   on fetched data.
1. Write the updated description with `bd update <issue_id> --body-file <path>`.

## Verification

- `external_tickets` entries reflect the updated state.
