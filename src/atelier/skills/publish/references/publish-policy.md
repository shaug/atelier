# Publish policy

Use this reference when executing publish, persist, or finalize workflows.

## Source of truth

- Use the workspace config (`config.sys.json` + `config.user.json`) for all
  publish decisions.
- Resolve settings with `scripts/resolve_publish_plan.py` and follow its output.
- Do not read or create `PERSIST.md`.

## Operation semantics

Definitions derived from workspace config:

- **publish**: run required checks, then publish per the config-derived plan. Do
  not finalize or tag.
- **persist**: save progress without finalizing. When `branch_pr` is false,
  persist is the same as publish.
- **finalize**: ensure publish is complete, integrate per history policy, push
  the default branch, then create the local finalization tag.

Branch mode mapping:

- `branch_pr = true`
  - **persist**: commit and push the workspace branch only (no PR).
  - **publish**: commit, push, and create/update the PR.
  - **finalize**: ensure publish is complete, integrate via PR, push the default
    branch, then tag.
- `branch_pr = false`
  - **publish/persist**: commit, integrate onto the default branch per
    `branch_history`, then push.
  - **finalize**: ensure publish is complete, then tag the default branch tip.

Publishing is complete only when the branch required by the plan is pushed.

If a push is rejected because the default branch moved, update your local
default branch and re-apply the workspace changes according to the history
policy (rebase/merge/squash), then push again.

## Invariants

- Run required checks from `repo/AGENTS.md` before publish/persist/finalize
  unless the user explicitly says to ignore failures.
- Keep the working tree clean before and after publish operations.
- Do not finalize without explicit user instruction.
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
