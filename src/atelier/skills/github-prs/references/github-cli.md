# GitHub CLI reference

Use this reference for provider-specific behavior when running the `github-prs`
scripts.

## Authentication

- `gh auth status` verifies authentication and the active GitHub host.
- Ensure the account has permission to read and edit PRs in the target repo.

## Commands used by scripts

- List PRs by head branch:
  `gh pr list --repo <repo> --head <head> --state <open|all> --json number,baseRefName,headRefName,state`
- View a PR:
  `gh pr view <number|branch> --repo <repo> --json number,url,state,baseRefName,headRefName,title,body,labels,isDraft,mergedAt,closedAt,updatedAt,reviewDecision,mergeable,mergeStateStatus`
- Create a PR:
  `gh pr create --repo <repo> --base <base> --head <head> --title <title> --body-file <path> --label <labels>`
- Edit a PR:
  `gh pr edit <number> --repo <repo> --title <title> --body-file <path> --base <base> --add-label <label> --remove-label <label>`

## JSON field notes

- `labels` is an array of objects containing `name`.
- `state` is typically `OPEN`, `CLOSED`, or `MERGED`.
- `mergedAt`, `closedAt`, and `updatedAt` are ISO-8601 timestamps when present.
- `reviewDecision` reflects the overall review state when available.
- `mergeable` is a string status from GitHub (for example `MERGEABLE`).
- `mergeStateStatus` is the merge queue/status summary (for example `DIRTY`).
