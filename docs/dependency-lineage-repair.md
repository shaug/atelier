# Dependency Lineage Repair

Use this runbook when dependency-linked changesets have collapsed
`changeset.parent_branch` metadata (for example, set to the epic root branch)
and downstream PRs are opening against the wrong base.

## Inspect

1. Identify affected epics and changesets:

```bash
bd list --label at:epic --status open
bd list --parent <epic-id> --status open
```

Changesets are leaf work beads (no work children) under the epic.

1. For each dependency-linked changeset, inspect lineage fields:

```bash
bd show <changeset-id>
```

Look for this corruption pattern:

- `changeset.parent_branch` equals the epic root branch.
- The changeset has dependency ids that point to another changeset.
- The dependency's `changeset.work_branch` does not match
  `changeset.parent_branch`.

## Repair

1. Set parent lineage to the dependency parent work branch:

```bash
bd update <changeset-id> --description "
...
changeset.parent_branch: <dependency-work-branch>
..."
```

1. Rerun finalize for the changeset so PR base/gate state is recalculated.

## Ambiguous lineage

When multiple dependency parents are possible:

1. Ensure each dependency changeset has `changeset.work_branch`.
1. Pick one deterministic parent and set `changeset.parent_branch` explicitly.
1. Keep remaining dependencies as non-lineage blockers.
1. Rerun worker finalize.
