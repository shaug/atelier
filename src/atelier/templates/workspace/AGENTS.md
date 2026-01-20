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
- Workspace intent and success criteria live in `WORKSPACE.md`.

## Required Reading

- `PROJECT.md` (if present) for project-level rules.
- `WORKSPACE.md` (if present) for workspace intent, scope, and completion
  criteria.
- `PERSIST.md` for how to finish and integrate this work (created for new
  workspaces).
- `BACKGROUND.md` (if present) for context when a workspace is created from an
  existing branch.

## Execution Expectations

- Complete the work described in `WORKSPACE.md` **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `WORKSPACE.md` rules take precedence over `PROJECT.md`.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
