---
name: publish
description: >-
  Publish, persist, or finalize an Atelier workspace by reading workspace config
  (config.sys.json + config.user.json) to decide PR vs direct integration and
  history policy, then running required checks, updating git/PR state, and
  creating finalization tags. Use when a user asks to
  publish/persist/finalize work, push workspace changes, integrate onto the
  default branch, or manage PR-based publishing for a workspace.
---

# Publish workspace work

## Inputs

- operation: `publish` | `persist` | `finalize`.
- workspace_root: path to the workspace root (default: `.`).
- repo_path: path to the workspace repo (default: `<workspace_root>/repo`).
- required_checks: explicit commands from `PROJECT.md` or `repo/AGENTS.md`.
- allow_check_failures: only if the user explicitly asks to ignore failures.

## Steps

1. Read policy sources: `PROJECT.md`, `repo/AGENTS.md`.
1. Load [references/publish-policy.md](references/publish-policy.md) for
   semantics, invariants, and recovery rules.
1. Resolve publish settings from workspace config:
   - Run
     `scripts/resolve_publish_plan.py --workspace <workspace_root> --operation <operation>`
     and capture `branch`, `branch_pr`, `branch_history`, and `default_branch`.
1. Ensure a clean working tree before changes:
   - Run `scripts/ensure_clean_tree.sh <repo_path>`.
1. Run required checks unless explicitly told to skip failures:
   - Run `scripts/run_required_checks.sh <repo_path> <command> [<command> ...]`.
1. Prepare commits with git as needed. Do not mutate state with `atelier`.
1. Execute the operation per the resolved plan:
   - If `branch_pr` is true, push the workspace branch for all operations, and
     use the `github-prs` skill to create/update PRs for publish/finalize.
     Integrate only on finalize.
   - If `branch_pr` is false, integrate onto `default_branch` per
     `branch_history` for publish/persist/finalize, then push the default
     branch.
1. For finalize, create the finalization tag:
   - Run `scripts/create_finalization_tag.sh <repo_path> <branch>`.
1. Verify results using read-only commands and git:
   - `atelier describe --format=json`
   - `atelier list --format=json`
   - `scripts/ensure_clean_tree.sh <repo_path>`

## Verification

- Required checks succeeded (or explicit user override recorded).
- Working tree is clean before and after mutations.
- Branch/PR state matches the workspace config-derived plan.
- Finalization tag exists locally after finalize.

## Failure paths

- If required checks fail and no explicit override exists, stop and report
  failures.
- If the working tree is dirty, stop and request cleanup or commit.
- If workspace config is missing `branch_pr` or `branch_history`, stop and
  request repair.
- If `default_branch` is required but missing, stop and request workspace config
  repair.
- If push or integration fails, follow recovery steps in
  [references/publish-policy.md](references/publish-policy.md).
- If the finalization tag already exists, stop and ask whether to keep it.
