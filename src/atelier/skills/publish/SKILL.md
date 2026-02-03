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
- worktree_path: path to the worktree (default: `.`).
- repo_path: path to the repo (default: `<worktree_path>`).
- root_branch: workspace root branch (from `ATELIER_WORKSPACE`).
- required_checks: explicit commands from `repo/AGENTS.md`.
- allow_check_failures: only if the user explicitly asks to ignore failures.

## Steps

1. Read policy sources: `repo/AGENTS.md`.
1. Load [references/publish-policy.md](references/publish-policy.md) for
   semantics, invariants, and recovery rules.
1. Resolve publish settings from project config:
   - Use `branch.pr`, `branch.history`, and the project default branch.
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
   - If `branch_pr` is true, push the changeset branch and use the `github-prs`
     skill to create/update PRs for publish/persist.
   - If `branch_pr` is false, integrate onto `default_branch` per
     `branch_history` for publish/persist, then push the default branch.
1. Verify results using read-only commands and git:
   - `atelier status --format=json`
   - `scripts/ensure_clean_tree.sh <repo_path>`

## Verification

- Required checks succeeded (or explicit user override recorded).
- Working tree is clean before and after mutations.
- Branch/PR state matches the project config-derived plan.
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
