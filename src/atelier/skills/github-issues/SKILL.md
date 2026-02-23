---
name: github-issues
description: >-
  Create, read, update, or close GitHub issues using deterministic gh CLI
  scripts. Use when a user asks to open a GitHub issue, fetch issue metadata,
  update an issue title/body/labels, or close an issue for a specific repo and
  issue id or URL.
---

# Manage GitHub issues

## Inputs

- repo: GitHub repository in `OWNER/REPO` form.
- issue: issue number or URL (required for read/update/close).
- title: issue title for create/update.
- body_file: path to a UTF-8 issue body file for create/update.
- labels: comma-separated label list; empty string clears labels.
- comment: optional closing comment when closing.
- reason: optional close reason (`completed` or `not planned`).
- state: optional list state (`open`, `closed`, `all`) for listing.
- search: optional search query for listing.
- limit: optional max results for listing.

## Steps

1. Confirm `gh` is available and authenticated for the target repo.
1. For create:
   - Run
     `scripts/create_issue.py --repo <repo> --title <title> --body-file <path> [--labels <labels>]`.
1. For read:
   - Run `scripts/read_issue.py --repo <repo> --issue <issue>`.
1. For list:
   - Run
     `scripts/list_issues.py --repo <repo> [--state <state>] [--search <search>] [--limit <limit>]`.
1. For update:
   - Run
     `scripts/update_issue.py --repo <repo> --issue <issue> [--title <title>] [--body-file <path>] [--labels <labels>]`.
1. For close:
   - Run
     `scripts/close_issue.py --repo <repo> --issue <issue> [--comment <comment>] [--reason <reason>]`.
1. For gh CLI usage and the JSON fields returned by the scripts, load
   [references/github-issues-gh.md](references/github-issues-gh.md).

## Outputs

- Scripts print issue metadata as JSON to stdout after each action.
- Body markdown transport must use `--body-file`, not inline shell text.
