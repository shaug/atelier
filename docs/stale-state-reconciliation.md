# Stale-State Reconciliation

`atelier gc --reconcile` now classifies stale-state findings with stable
operator buckets before it mutates Beads metadata:

- `metadata-stale`
  - Live PR evidence is terminal (`merged` or `closed`), but Beads still has a
    non-terminal `status` and/or stale `pr_state`.
  - Expected action: rerun reconcile/finalize so metadata can converge.
- `not-merged`
  - Live PR lifecycle is still active, or terminal proof is not available.
  - Expected action: leave the changeset active and wait for publish/merge
    evidence instead of forcing closure.
- `decision-required`
  - PR lookup, branch metadata, or lineage proof is ambiguous.
  - Expected action: repair the missing proof, then rerun reconcile.

Example diagnostics:

```text
triage=metadata-stale reason=terminal_pr_merged live_pr=merged stored_pr=draft-pr stale_fields=status,pr_state action=reconcile-stale-metadata
triage=not-merged reason=active_pr_lifecycle_pr-open live_pr=pr-open stored_pr=merged action=leave-state-as-is
triage=decision-required reason=pr_lifecycle_lookup_failed detail=gh timeout action=manual-decision-required
```

When output lands in `decision-required`, use a deterministic repair path:

1. Inspect the changeset metadata with `bd show <changeset-id>`.
1. Verify `changeset.work_branch`, `changeset.parent_branch`, `pr_state`, and
   `changeset.integrated_sha`.
1. If the blocker is dependency lineage or `unknown-parent`, repair the single
   deterministic parent branch using
   [`docs/dependency-lineage-repair.md`](./dependency-lineage-repair.md).
1. Rerun `atelier gc --reconcile --dry-run` to confirm the bucket changes away
   from `decision-required` before applying the real reconcile run.
