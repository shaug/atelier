# Atelier Project Overlay

This project is managed using **Atelier**, a workspace-based workflow for
agent-assisted development.

## How Work Is Organized

- Development work is performed in isolated **workspaces**
- Workspaces live under the Atelier project directory managed in the local data
  dir
- Each workspace represents **one unit of work**
- Each workspace has its own `WORKSPACE.md` defining intent and scope

## Authority

- This file describes only the **Atelier workflow overlay**
- Workspace `WORKSPACE.md` files define execution expectations
- Repository-specific coding conventions are defined elsewhere (e.g. a
  repository-level `AGENTS.md`, if present)

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in a workspace, read it and apply the rules
defined there as well.

In case of conflict:

- `WORKSPACE.md` rules take precedence over `PROJECT.md`

- `PROJECT.md` rules take precedence over this file

- Atelier project metadata lives in the local data directory (not in the repo).
