---
name: github-prs
description: >-
  Create, update, retarget, and inspect GitHub pull requests with deterministic
  scripts and the GitHub CLI. Use when Codex needs to open or update a PR for a
  branch, set PR title/body/labels, retarget a PR base branch, or read PR status
  and metadata for a specific repo/head/base.
---

# Manage GitHub pull requests

## Inputs

- repo: GitHub repository slug (e.g., `owner/name`).
- base: base branch name for the PR (target branch).
- head: head branch name for the PR (source branch).
- title: PR title string.
- body_file: path to a UTF-8 PR body file.
- labels: comma-separated label list (use an empty string to clear labels).
- pr_number: PR number for review-thread operations.

## Steps

1. Read [references/github-cli.md](references/github-cli.md) for GitHub CLI
   behavior and JSON field notes.
1. Create or update a PR with:
   `scripts/create_or_update_pr.py --repo <repo> --base <base> --head <head> --title <title> --body-file <path> --labels <labels>`
1. Retarget the PR base branch with:
   `scripts/retarget_pr_base.py --repo <repo> --head <head> --base <base>`
1. Read PR status/metadata with:
   `scripts/read_pr_status.py --repo <repo> --head <head>`
1. For review feedback on inline comments:
   - List unresolved review threads:
     `scripts/list_review_threads.py --repo <repo> --pr-number <pr_number>`
   - Reply inline (do not post a top-level PR comment):
     `scripts/reply_inline_thread.py --repo <repo> --comment-id <comment_id> --thread-id <thread_id> --body-file <path>`
   - Resolve the review thread after replying (done by `--thread-id` above).

## Invariants

- Provide all parameters explicitly; do not infer repo, base, or head.
- Pass markdown bodies via file (`--body-file`) rather than inline shell text.
- Keep label updates deterministic by matching the exact label set provided.
- Fail fast when no matching PR exists for an update or status read.
- When feedback comes from inline review comments, reply inline to that comment
  and resolve the same thread.

## Prohibited actions

- Do not mutate local git state or push branches.
- Do not edit files outside of explicit PR metadata operations.
- Do not modify repository settings or secrets.
- Do not replace inline-thread replies with new top-level PR comments.

## Allowed verification calls

- `gh pr view <number|branch> --repo <repo> --json ...`
