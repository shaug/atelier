---
name: import-legacy-tickets
description: >-
  Trigger startup legacy Beads import/migration on demand and report whether
  migration was performed or skipped.
---

# Import legacy tickets

## Inputs

- beads_dir: Optional Beads store path.

## Steps

1. Run:
   - `python3 skills/import-legacy-tickets/scripts/import_legacy_tickets.py`
   - or
     `python3 skills/import-legacy-tickets/scripts/import_legacy_tickets.py --beads-dir "<path>"`
1. Return the script output verbatim so operators can see migration/import
   diagnostics and startup state before/after.

## Verification

- Startup migration/import flow was executed through Atelier Beads runtime.
- Output clearly states one of: `migrated`, `skipped`, or `blocked`.
- Output includes startup-state diagnostics for before and after execution.
