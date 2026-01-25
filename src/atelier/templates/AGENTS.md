<!--
AGENTS.md

This file is managed by Atelier. Do not edit it directly.
-->

# Atelier Agent Contract

This project uses **Atelier**, a workspace-based workflow for agent-assisted
development.

## How Work Is Organized

- Work happens in isolated workspaces under the Atelier data directory.
- Each workspace maps to one git branch and includes a `repo/` checkout.
- Workspace intent and success criteria live in `SUCCESS.md`.
- All Atelier policy files for this workspace live alongside this file.

## Required Reading

- `PROJECT.md` (if present) for project-wide rules that apply to every
  workspace; it is linked/copied into this workspace.
- `SUCCESS.md` for workspace-specific intent, scope, and completion criteria.
- `PERSIST.md` for how to finish and integrate this work, based ont he project's
  integration strategy with git and its remote repository.
- `BACKGROUND.md` (if present) for context when a workspace is created from an
  existing branch.

## Execution Expectations

- Complete the work described in `SUCCESS.md` **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.
- After integration (as specified in `PERSIST.md`), create the local
  finalization tag `atelier/<branch-name>/finalized` (do not push);
  `atelier clean` relies on it.

## Publishing and Finalization Commands

- Before publish/persist/finalize, run the required workspace checks
  (tests/formatting/linting/etc.) described in `PROJECT.md`, `SUCCESS.md`, or
  the repo's `AGENTS.md`. Do not proceed if they fail unless the user explicitly
  asks to ignore the failures.
- "publish" means publish only; do not finalize or tag.
- "persist" means save progress to the remote per the publish model without
  finalizing; when `branch.pr` is false, treat this the same as "publish"; when
  `branch.pr` is true, commit and push to the workspace branch but do not create
  or update a PR.
- When `branch.pr` is true, "publish" means commit, push, and create or update
  the pull request.
- "finalize" means ensure the workspace is published first (perform publishing
  if needed), then integrate onto the default branch (merge a PR or rebase/merge
  as configured), push, and tag only after publishing is complete.
- When `branch.pr` is false, publishing is not complete until the default branch
  is pushed to the remote.
- When `branch.pr` is false, if publishing fails because the default branch
  moved, update/rebase per the history policy and retry before finalizing.

Ensure the configured agent CLI is installed and authenticated (see
`agent.default`).

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `SUCCESS.md` rules take precedence over `PROJECT.md`.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
