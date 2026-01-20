<!-- atelier:{workspace_id} -->

# Atelier Workspace

This directory is an **Atelier workspace**.

## Workspace Model

- This workspace represents **one unit of work**
- All code changes for this work should be made under `repo/`
- The code in `repo/` is a real git repository and should be treated normally
- This workspace maps to **one git branch**
- Integration expectations are defined below
- Workspace intent and success criteria are defined in `WORKSPACE.md`

## Execution Expectations

- Complete the work described in `WORKSPACE.md` **to completion**
- Do not expand scope beyond what is written there
- Prefer small, reviewable changes over large refactors
- Avoid unrelated cleanup unless explicitly required
- Read `WORKSPACE.md` before beginning work

## Agent Context

When operating in this workspace:

- Treat this workspace as the **entire world**
- Do not reference or modify other workspaces
- Read `WORKSPACE.md` and the remainder of this file carefully before beginning
  work

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in this workspace, read it and apply the rules
defined there as well.

In case of conflict:

- `WORKSPACE.md` rules take precedence over `PROJECT.md`
- `PROJECT.md` rules take precedence over this file

{integration_strategy}

After reading `WORKSPACE.md`, proceed with the work described there.
