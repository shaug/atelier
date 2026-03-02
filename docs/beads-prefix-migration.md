# Beads Prefix Migration

This project supports per-project Beads prefixes via `beads.prefix`.

## Existing Projects (`at` -> custom prefix)

1. Re-run init and choose a new prefix:
   - `atelier init --beads-prefix ts`
1. Atelier updates Beads config and runs prefix repair:
   - `bd config set issue_prefix ts`
   - `bd rename-prefix ts- --repair`
1. Validate store health and identity:
   - `bd prime`
   - `bd doctor --fix --yes`
   - `bd list --label ts:epic --all --limit 0`
1. Validate lifecycle parity:
   - `atelier status`
   - Confirm expected epics/changesets and no missing epic identity warnings.

## Notes

- Prefixes are collision-checked against other local Atelier projects during
  setup.
- Suggested prefixes are deterministic (`tuber-service` -> `ts`, then `ts2`,
  `ts3`, ... when collisions exist).
- Runtime lookup remains compatibility-safe for legacy `at:*` labels while
  migrating.
