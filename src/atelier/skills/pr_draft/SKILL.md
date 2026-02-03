---
name: pr_draft
description: >-
  Draft a pull request title and body for a changeset branch using the
  standard template. Use when preparing a PR summary for a changeset.
---

# PR draft

## Inputs

- changeset_id: Bead id of the changeset.
- worktree_path: path to the changeset worktree (default: `.`).
- repo_path: path to the repo (default: `<worktree_path>`).
- root_branch: epic root branch (from bead metadata).
- parent_branch: parent branch for the changeset (from bead metadata).
- work_branch: changeset work branch (from bead metadata).
- template_path: template file path (default: `references/pr-template.md`).

## Steps

1. Read the changeset bead and capture its title/description.
1. Collect the diff summary against `root_branch`:
   - `git -C <repo_path> diff --stat <root_branch>...<work_branch>`
1. Open the template and fill it using:
   - Changeset description (scope, intent, constraints).
   - Actual code changes (from diff + files touched).
   - Tests executed (if any). If none, state why.
1. Produce:
   - PR title (clear, imperative).
   - PR body (filled template).
1. Output the title/body only. Do not create or update the PR.

## Guardrails

- Keep the PR body factual and bounded to the changeset scope.
- If the diff is large or unclear, call it out explicitly in the notes.
- Do not modify code, commits, or beads.

## Verification

- PR title is concise and matches the changeset scope.
- Template sections are populated or explicitly marked as not applicable.
