---
name: external-close
description: >-
  Apply external close actions for a bead's linked tickets when requested.
  Use when closing an epic/changeset that should update external systems.
---

# Close external tickets

## Inputs

- issue_id: Bead id being closed.
- provider: Provider name to close (optional).
- close_action: `comment` | `close` | `sync` | `none` (from external_tickets).
- beads_dir: Optional Beads store path.

## Steps

1. Show the bead and parse `external_tickets` entries.
1. For each entry, obey `on_close`:
   - `comment`: add a comment with final status.
   - `close`: close the external ticket.
   - `sync`: perform provider-specific sync.
   - `none`: no external action.
1. Update the `state` value in `external_tickets` if changes were made.

## Verification

- External actions executed only when explicitly requested and configured.
