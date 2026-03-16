---
name: external-sync
description: >-
  Synchronize external ticket state for Beads issues when explicitly requested.
  Use when a user wants to refresh state or mirror changes.
---

# Sync external ticket state

## Inputs

- issue_id: Bead id to sync (epic or changeset).
- provider: Provider name to sync (optional; sync all if omitted).
- include_state: Optional boolean to refresh cached state (default true).
- include_body: Optional boolean to refresh cached body/title (default false).
- include_notes: Optional boolean to refresh cached notes/summary (default
  false).
- beads_dir: Optional Beads store path.

## Steps

1. Read [Publish Store Migration Contract] before mutating ticket metadata.
1. Show the bead and parse `external_tickets` entries.
1. For each entry, optionally call provider-specific tooling (e.g., GitHub or
   Linear skills) to fetch current state/content if the user asks for it.
1. Update the `state` and `state_updated_at` values in `external_tickets` when
   `include_state` is true.
1. When `include_body` or `include_notes` is true, update cached
   `title`/`summary`/`body`/`notes` plus `content_updated_at` and
   `notes_updated_at` as appropriate.
1. Persist the refreshed `external_tickets` payload through
   `atelier.store.UpdateExternalTicketsRequest` rather than writing the
   description directly with `bd update`.

## Verification

- `external_tickets` entries reflect the updated state.

<!-- inline reference link definitions. please keep alphabetized -->

[publish store migration contract]: ../../../docs/publish-store-migration-contract.md
