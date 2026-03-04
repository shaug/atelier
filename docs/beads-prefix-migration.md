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

## Operator Runbook: Prefix-Migration Drift

Use `atelier doctor` after prefix migration when worker startup reports lineage
or worktree-mapping drift (for example
`...already set; override not permitted`).

### Pre-run backup

Capture both planning metadata and worktree mapping files before any mutation:

```bash
cp -R "<project beads root>" beads-root-backup
cp -R "<project data dir>/worktrees/.meta" worktrees-meta-backup
```

### Detect only (default; read-only)

Run a single read-only pass for the project:

```bash
atelier doctor
```

Interpretation:

- `atelier doctor` reports three deterministic check families:
  - `prefix_migration_drift`
  - `startup_blocking_lineage_consistency`
  - `in_progress_integrity_signals`
- Prefix drift remains the only mutating check family and reports canonical
  root/work/worktree repair targets.
- Startup-blocking lineage findings stay read-only and explicitly mark
  metadata/mapping conflicts that can block worker startup.
- In-progress integrity findings stay read-only and surface ownership/hook
  inconsistencies.
- `--fix` remains scoped to prefix-migration drift repair only.

For machine-readable output:

```bash
atelier doctor --format json
```

### Convergence validation harness

Run the deterministic regression harness for representative migrated projects:

```bash
uv run pytest tests/atelier/test_prefix_migration_convergence.py -v
```

Coverage matrix:

- `tuber-service`: validates startup block on legacy mapping drift,
  deterministic doctor findings, and convergence after `--fix`.
- `gumshoe`: validates the same flow with an independent migrated-project
  lineage fixture.
- `eldritchdark`: validates the same flow for a third fixture to guard against
  single-project assumptions.

### Normalization decision points

Use this decision order for operational triage:

1. Run `atelier doctor` (read-only) and confirm whether
   `prefix_normalization.required` is `true`.
1. If `required` is `false`, stop; no migration repair action is needed.
1. If `required` is `true`, capture backups first (Beads root and
   `worktrees/.meta`).
1. Apply `atelier doctor --fix` only when no active hooks are present, or when
   `--force` is explicitly justified.
1. Re-run `atelier doctor` and verify `prefix_normalization.required` is
   `false`.

### Apply repairs (explicit opt-in)

Mutation is never implicit. Apply only with `--fix`:

```bash
atelier doctor --fix
```

By default, `--fix` refuses to run while active agent hooks are present to avoid
racing worker startup/finalization writes. Use `--force` only when you have
confirmed this override is safe:

```bash
atelier doctor --fix --force
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
rm -rf "<project beads root>"
cp -R beads-root-backup "<project beads root>"
rm -rf "<project data dir>/worktrees/.meta"
cp -R worktrees-meta-backup "<project data dir>/worktrees/.meta"
atelier doctor
```

### GC behavior

`atelier doctor` does not run `atelier gc` and introduces no default GC side
effects. GC remains a separate explicit operation.

### Legacy-compatible vs fully normalized state

Fully normalized:

- `changeset.root_branch`, `changeset.work_branch`, and `worktree_path` match
  canonical post-migration values.
- Worktree mapping entries under `worktrees/.meta` match lineage metadata.
- `atelier doctor` reports no prefix-drift findings for the project.

Intentionally legacy-compatible:

- Read-only detection accepts legacy artifacts as input evidence for diagnosis.
- Repair remains explicit (`atelier doctor --fix`), never implicit at startup.
- Lifecycle/runtime labels remain fixed to `at:*` and do not fall back to
  generalized custom-prefix label matching.

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
