<!--
AGENTS.md

This file is managed by Atelier. Do not edit it directly.
-->

# Atelier Agent Contract

This project uses **Atelier**, a workspace-based workflow for agent-assisted
development.

## How Work Is Organized

- Work happens in isolated worktrees under the Atelier data directory.
- Each workspace is associated with a top-level Bead (epic) and its changesets.
- Beads are the source of truth for intent, scope, and status.
- All Atelier policy files for this workspace live alongside this file.

## Required Reading

- The epic bead (and its changesets) for workspace intent, scope, and completion
  criteria.
- Project policy (if present) for agent-wide rules.
- `BACKGROUND.md` (if present) for context when a workspace is created from an
  existing branch.
- `repo/AGENTS.md` (if present) for repository-specific rules.

## Skills

- Atelier-managed skills live under `./skills/` in the workspace.
- Each skill directory contains an authoritative `SKILL.md`.
- Skills under `./skills/` must not be modified.
- If a skill name conflicts with external tools or global skills, the
  Atelier-managed skill takes precedence.

## Execution Expectations

- Complete the work described in the epic bead **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.
- After integration (as guided by the `publish` skill), create the local
  finalization tag `atelier/<branch-name>/finalized` (do not push);
  `atelier clean` relies on it.

## Publishing and Finalization Commands

- Before publish/persist/finalize, run the required workspace checks
  (tests/formatting/linting/etc.) described in the repo's `AGENTS.md`. Do not
  proceed if they fail unless the user explicitly asks to ignore the failures.
- Use the `publish` skill for publish/persist/finalize semantics derived from
  the workspace config.

Ensure the configured agent CLI is installed and authenticated (see
`agent.default`).

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- Epic bead rules take precedence over `repo/AGENTS.md`.
- `repo/AGENTS.md` rules take precedence over this file.

Before finalizing work in a workspace, use the `publish` skill.

After reading the applicable files, proceed with the work described there.
