# Event History Overflow Recovery

Beads issue mutation can fail closed when the historical event payload for one
issue grows past the backing store's `old_value` column limit. When this
happens, planner and worker flows now surface the same explicit repair action:

```bash
atelier repair-event-history-overflow <issue-id>
```

## When To Run It

Run the command when planner startup, publish/finalize metadata writes, or
worker lifecycle updates fail with an
`event-history overflow blocked the mutation` diagnostic.

Common symptoms:

- review metadata updates fail while moving a changeset to `draft-pr`,
  `in-review`, `approved`, or `merged`
- worker lifecycle writes fail while marking a changeset blocked or closed
- the error detail mentions a value being too large for the Beads `old_value`
  column

## What The Command Does

The repair command keeps the existing recovery contract explicit and
deterministic:

1. Primes the project-scoped Beads store.
1. Creates a verified SQLite backup before mutating a SQLite-backed store.
1. Compacts oversized historical notes for the target issue.
1. Verifies that the issue is mutable again before reporting success.
1. Prints backend-specific guidance for inspecting pre-repair content.

For Dolt-backed stores, the output points operators at `bd history` and
`bd restore`. For SQLite-backed stores, the output reports the backup path to
inspect if the full pre-repair notes are needed.

## After Repair

Rerun the blocked planner or worker operation after the repair command reports
`verified_mutable: true` or the table output says the issue is mutable again.

If the command reports that repair evidence did not prove convergence, stop and
fail closed. Preserve the reported backup or history path and investigate the
issue-specific Beads state before attempting more mutations.
