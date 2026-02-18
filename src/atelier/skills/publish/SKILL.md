---
name: publish
description: >-
  Publish or persist an Atelier changeset by reading project config to decide
  PR vs direct integration and history policy, then running required checks and
  updating git/PR state. Use when a user asks to
  publish/persist work, push changeset branches, integrate onto the default
  branch, or manage PR-based publishing for a changeset.
---

# Publish workspace work

## Inputs

- operation: `publish` | `persist`.
- changeset_id: changeset bead id for metadata updates.
- worktree_path: path to the worktree (default: `.`).
- repo_path: path to the repo (default: `<worktree_path>`).
- root_branch: epic root branch (from bead metadata).
- parent_branch: parent branch for the changeset (from bead metadata).
- work_branch: changeset work branch (from bead metadata).
- pr_strategy: project PR strategy (e.g., sequential).
- required_checks: explicit commands from `repo/AGENTS.md`.
- allow_check_failures: only if the user explicitly asks to ignore failures.

## Steps

1. Read policy sources: `repo/AGENTS.md`.
1. Load [references/publish-policy.md](references/publish-policy.md) for
   semantics, invariants, and recovery rules.
1. Resolve publish settings from project config:
   - Use `branch.pr`, `branch.history`, and the project default branch.
1. Resolve changeset metadata (root/parent/work branches and PR strategy) from
   bead descriptions or environment.
1. Determine whether PR creation is allowed by the PR strategy:
   - `sequential`: allow only when the parent PR state is `merged` or `closed`
     (or when there is no parent PR).
   - `on-ready`: allow when parent is not merely `pushed` (no parent,
     draft/open/review/approved/merged/closed are allowed).
   - `parallel`: allow immediately.
   - If PR creation is blocked, record the reason and skip PR creation.
1. Ensure a clean working tree before changes:
   - Run `scripts/ensure_clean_tree.sh <repo_path>`.
1. Check changeset size against guardrails:
   - Run `git -C <repo_path> diff --numstat <root_branch>...HEAD`.
   - Sum added + deleted lines; if >800 LOC without approval, stop and send a
     `NEEDS-DECISION:` message to the overseer.
1. Run required checks unless explicitly told to skip failures:
   - Run `scripts/run_required_checks.sh <repo_path> <command> [<command> ...]`.
1. Prepare commits with git as needed. Do not mutate state with `atelier`.
1. Execute the operation per the resolved plan:
   - Rebase the work branch onto `root_branch` before any integration or PR.
   - If `branch_pr` is true:
     - Push the work branch.
     - If PR creation is allowed, run `pr_draft` to generate the title/body,
       then use the `github-prs` skill to create/update the PR.
     - If PR creation is gated, report the reason and exit after pushing.
   - If `branch_pr` is false:
     - Integrate the rebased work branch onto `root_branch` per `branch_history`
       (rebase/merge/squash).
     - Push the updated `root_branch`.
1. Persist integration metadata on the changeset bead:
   - If integration occurred (non-PR flow) or a PR merged (PR flow), set
     `changeset.integrated_sha` to the integrated commit SHA in the bead
     description using `bd update --body-file ...`.
   - Do not set `changeset.integrated_sha` for `persist` runs that did not
     integrate or merge.
   - If the integrated SHA cannot be determined, send `NEEDS-DECISION` and stop.
1. Verify results using read-only commands and git:
   - `atelier status --format=json`
   - `scripts/ensure_clean_tree.sh <repo_path>`

## Verification

- Required checks succeeded (or explicit user override recorded).
- Working tree is clean before and after mutations.
- Branch/PR state matches the project config-derived plan and PR strategy.
- `changeset.integrated_sha` is present when integration/merge occurred.
- Repo is clean after publish/persist.

## Failure paths

- If required checks fail and no explicit override exists, stop and report
  failures.
- If the working tree is dirty, stop and request cleanup or commit.
- If project config is missing `branch_pr` or `branch_history`, stop and request
  repair.
- If `default_branch` is required but missing, stop and request project config
  repair.
- If push or integration fails, follow recovery steps in
  [references/publish-policy.md](references/publish-policy.md).
- Do not merge a PR unless explicitly requested.
