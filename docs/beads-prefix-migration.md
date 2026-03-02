# Beads Prefix Migration

This project supports per-project Beads prefixes via `beads.prefix`.

## Existing Projects (`at` -> custom prefix)

1. Re-run init and choose a new prefix:
   - `atelier init --beads-prefix ts`
1. Atelier runs prefix repair before final prefix verification:
   - `bd rename-prefix ts- --repair`
   - if needed, `bd config set issue_prefix ts`
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
- Atelier-managed lifecycle/runtime labels use fixed `at:*` names.
- Legacy non-`at:*` compatibility in this changeset is limited to agent-label
  lookup fallback only.
- Epic identity and runtime lifecycle labels (`at:epic`, `at:message`,
  `at:unread`, `at:hooked`) are fixed to `at:*` with no broad prefixed fallback.
