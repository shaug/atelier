# Dependency Lineage Repair

Use this runbook when dependency-linked changesets have collapsed
`changeset.parent_branch` metadata (for example, set to the epic root branch)
and downstream PRs are opening against the wrong base.

## Inspect

Run the repair tool in report mode first:

```bash
python src/atelier/skills/publish/scripts/repair_dependency_lineage.py \
  --repo-root . \
  --beads-root "$BEADS_DIR"
```

The report shows two states:

- `FIX`: deterministic dependency parent branch was resolved.
- `BLOCKED`: lineage is ambiguous or dependency metadata is incomplete.

## Apply deterministic fixes

When report output looks correct, apply repairs:

```bash
python src/atelier/skills/publish/scripts/repair_dependency_lineage.py \
  --repo-root . \
  --beads-root "$BEADS_DIR" \
  --apply
```

You can scope to one epic:

```bash
python src/atelier/skills/publish/scripts/repair_dependency_lineage.py \
  --repo-root . \
  --beads-root "$BEADS_DIR" \
  --epic at-epic \
  --apply
```

## Follow-up for blocked rows

For `BLOCKED` rows, fix metadata manually before rerunning:

1. Ensure each dependency changeset has `changeset.work_branch`.
1. Remove ambiguous dependency-parent candidates or set an explicit
   `changeset.parent_branch`.
1. Rerun the repair tool and then rerun worker finalize.
