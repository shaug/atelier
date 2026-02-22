---
name: pr-draft
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
- ticket_section_script: helper script path (default:
  `scripts/render_tickets_section.py`).

## Steps

1. Read the changeset bead and capture its title/description.
1. Collect the diff summary against `root_branch`:
   - `git -C <repo_path> diff --stat <root_branch>...<work_branch>`
1. Open the template and fill it using:
   - Changeset description (scope, intent, constraints).
   - Actual code changes (from diff + files touched).
   - Tests executed (if any). If none, state why.
1. Render ticket references from bead metadata:
   - `python3 <ticket_section_script> --changeset-id <changeset_id> --repo-path <repo_path>`
   - If output is non-empty, include it as the `## Tickets` section.
   - If output is empty, remove the `## Tickets` section entirely.
1. Produce:
   - PR title (clear, imperative).
   - PR body (filled template).
1. Output the title/body only. Do not create or update the PR.

## Guardrails

- Keep the PR body factual and bounded to the changeset scope.
- Never mention bead ids in title/body.
- Reference only external tickets in `## Tickets`.
- If the diff is large or unclear, call it out explicitly in the notes.
- Do not modify code, commits, or beads.

## Verification

- PR title is concise and matches the changeset scope.
- Template sections are populated or explicitly marked as not applicable.
- `## Tickets` is present only when external tickets are linked.
