---
name: plan-split-tasks
description: >-
  Split an epic or changeset into child changesets with deterministic
  refinement-lineage propagation.
---

# Plan split tasks

Use this only when the epic should be decomposed. If the epic itself is a single
review-sized unit, keep it as the executable changeset.

## Inputs

- parent_id: Parent epic or changeset bead id to split.
- tasks: List of `"<title>::<acceptance>"` entries (`--task` repeatable).
- status: Optional initial status for created children (`deferred|open`).
- beads_dir: Optional Beads store path.
- repo_dir: Optional repo root override. Defaults to `./worktree` then cwd.

## Steps

1. Confirm decomposition is necessary for scope, dependency sequencing, or
   reviewability.
1. If decomposition would create exactly one child changeset, keep the epic as
   the executable changeset unless explicit decomposition rationale is recorded
   in notes/description.
1. Create split changesets with the script:
   - `python skills/plan-split-tasks/scripts/split_tasks.py --parent-id "<parent_id>" --task "<title>::<acceptance>" [--task "<title>::<acceptance>"] [--status deferred|open] [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"]`
1. Keep child split units scoped and reviewable.
1. If parent lineage has required refinement metadata, each created child gets
   authoritative inherited `planning_refinement.v1` metadata.
1. Use `--notes` or `--append-notes` for follow-up details instead of editing
   descriptions.

## Verification

- All executable work items are leaf work beads (changesets by graph inference).
- One-child decompositions include explicit rationale.
- Refined parent lineage remains refined across all split descendants.
