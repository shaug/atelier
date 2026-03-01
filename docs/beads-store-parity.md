# Beads Store Parity and Recovery

Atelier planning/work execution defaults to the project-scoped Beads store:

- `<atelier-project-dir>/.beads`

Repository-local stores such as `<repo>/.beads` are external sources and are not
the default planning store.

## One-shot parity check

Run these commands from a project worktree to verify planner/worker parity:

```bash
python3 src/atelier/skills/planner-startup-check/scripts/refresh_overview.py --agent-id "$ATELIER_AGENT_ID"
atelier work --mode auto --dry-run
```

Verify both outputs report:

- the same Beads root path
- the same total epic count

If counts differ, you are likely reading different Beads stores.

## Explicit override diagnostics

Planner startup, epic listing, and legacy import scripts accept
`--beads-dir "<path>"`. When the override points at a non-project store, they
emit a warning with both paths:

- `project_beads_root=<project path>`
- `override_beads_root=<override path>`

## Migration and recovery playbook

1. Confirm the project-scoped store path:
   - `atelier status --format=json`
   - Inspect `beads_root` in the output.
1. Prime and repair the project store:
   - `BEADS_DIR="<project beads root>" bd doctor --fix --yes`
   - `BEADS_DIR="<project beads root>" bd prime`
1. If startup reports legacy SQLite migration eligibility, run:
   - `python3 src/atelier/skills/import-legacy-tickets/scripts/import_legacy_tickets.py`
1. Re-run the one-shot parity check above.
1. If divergence persists, stop using overrides and share the warning lines with
   the planner/operator so the mismatched stores can be reconciled.
