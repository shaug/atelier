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

## Prefix-Migration Drift Doctor

Use `atelier doctor` after prefix migration when worker startup reports lineage
or worktree-mapping drift (for example
`...already set; override not permitted`).

### Pre-run backup

Capture both planning metadata and worktree mapping files before any mutation:

```bash
BEADS_DIR="<project beads root>" bd export > beads-backup.jsonl
cp -R "<project data dir>/worktrees/.meta" worktrees-meta-backup
```

### Detect only (default; read-only)

Run a single read-only pass for the project:

```bash
atelier doctor
```

Interpretation:

- `Drifted changesets`: changesets with branch/path conflicts.
- `Changesets needing updates`: subset where canonicalization would change
  metadata or mapping state.
- The details table lists canonical root/work/worktree values and whether the
  run `would update` each target.

For machine-readable output:

```bash
atelier doctor --format json
```

### Apply repairs (explicit opt-in)

Mutation is never implicit. Apply only with `--fix`:

```bash
atelier doctor --fix
```

The command updates only affected records (changeset lineage metadata and
worktree mapping entries). Unaffected changesets are not modified.

### Rollback

If the repair run should be reverted:

1. Restore Beads from backup.
1. Restore worktree mapping metadata from backup.
1. Re-run `atelier doctor` (read-only) to confirm drift state is back to the
   expected baseline.

Example restore flow:

```bash
cp -R worktrees-meta-backup "<project data dir>/worktrees/.meta"
# Re-import or otherwise restore beads-backup.jsonl with your project's
# standard Beads recovery flow.
atelier doctor
```

### GC behavior

`atelier doctor` does not run `atelier gc` and introduces no default GC side
effects. GC remains a separate explicit operation.

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
