# Publish policy

Use this reference when executing publish or persist workflows.

## Source of truth

- Use the project config (`config.sys.json` + `config.user.json`) for all
  publish decisions.
- Do not read or create `PERSIST.md`.

## Operation semantics

Definitions derived from project config and bead metadata:

- **publish**: run required checks, then publish per the config-derived plan and
  PR strategy.
- **persist**: save progress without integrating. When `branch_pr` is false,
  persist is the same as publish.

Branch mode mapping:

- `branch_pr = true`
  - **persist**: commit and push the changeset branch only (no PR).
  - **publish**: commit, push, and create/update the PR when allowed by the PR
    strategy (otherwise push only).
- `branch_pr = false`
  - **publish/persist**: commit, integrate onto the epic `root_branch` per
    `branch_history`, then push the root branch.

Changeset metadata:

- After a successful integration or merged PR, update the changeset bead field
  `changeset.integrated_sha` to the integrated commit SHA.
- For non-integrating persist runs, do not set `changeset.integrated_sha`.
- If you cannot determine the integrated SHA deterministically, send
  `NEEDS-DECISION` and stop.

Publishing is complete only when the branch required by the plan is pushed.

If a push is rejected because the root branch moved, update your local root
branch and re-apply the workspace changes according to the history policy
(rebase/merge/squash), then push again.

## Invariants

- Run required checks from `repo/AGENTS.md` before publish/persist unless the
  user explicitly says to ignore failures.
- Keep the working tree clean before and after publish operations.
- The skill owns mutation; `atelier` may only be used for read-only
  verification.

## Prohibited actions

- Do not invoke `atelier` to mutate state.
- Do not modify skill files or templates as part of publish.

## Allowed verification calls

- `atelier status --format=json`
- `atelier list --format=json`

## PR coordination

When `branch_pr` is true, delegate PR creation or updates to the `github-prs`
skill. Validate results after mutation.

PR strategy default: sequential (one PR at a time, defer PR creation until the
epic is ready for review). When the strategy blocks PR creation, push the branch
and exit without opening a PR.

When PR creation is allowed, draft the PR title/body with the `pr_draft` skill
and hand the result to `github-prs`. When PR creation is gated, report the
reason and skip PR creation after pushing the branch.
