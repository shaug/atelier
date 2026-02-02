# Atelier Behavior and Design Notes

This document captures the current behavior of the Atelier CLI. It is a compact
overview; command-specific details live in module docstrings under
`src/atelier/commands`.

## Purpose

Atelier is a local CLI for workspace-based development inside a single Git repo
at a time. Each workspace is a unit of intent with its own worktree checkout and
changeset branches.

Atelier prioritizes explicit intent, predictable filesystem layout, and minimal
side effects inside the user's repo.

## Core concepts

- **Project**: Identified by the absolute path to a local enlistment. Project
  state lives under the Atelier data directory.
- **Epic**: Top-level unit of intent that owns a workspace root branch.
- **Changeset**: Child unit under an epic; each changeset is a branch derived
  from the root branch.
- **Workspace root branch**: User-facing branch name for the epic. Stored as
  `workspace.root_branch` in epic metadata and labeled
  `workspace:<root_branch>`.
- **Worktree**: A per-epic git worktree checkout stored under the data
  directory. Worktree mappings live under `worktrees/.meta/`.
- **Worktree path**: Stored as `worktree_path` in epic metadata once created.
- **Changeset labels**: Changesets use `cs:planned`, `cs:ready`,
  `cs:in_progress`, `cs:merged`, and `cs:abandoned` to capture non-derivable
  lifecycle state.

## Filesystem layout

Project directory (under the Atelier data dir):

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ config.sys.json
      ├─ config.user.json
      ├─ templates/
      │  └─ AGENTS.md
      └─ worktrees/
         ├─ .meta/
         │  └─ <epic-id>.json
         └─ <epic-id>/
            └─ <git worktree checkout>
```

Notes:

- `<project-key>` is the enlistment basename plus a short hash of the full
  enlistment path.
- Worktrees are keyed by epic id; mappings live in `worktrees/.meta/`.

## Configuration

Atelier splits configuration into two JSON files at the project level:

- `config.sys.json` (system-managed): IDs, timestamps, managed-file hashes, and
  other metadata.
- `config.user.json` (user-managed): branch prefix, agent/editor configuration,
  and per-project preferences.

Editor roles:

- `editor.edit` for blocking edits.
- `editor.work` for opening worktrees in an editor.

Branch prefix:

- Used during planning to suggest root branch names.
- Used during fuzzy resolution when the user types a workspace name.

## Templates and policy files

- `AGENTS.md` is managed from the project templates and used as the agent
  prologue.
- No `SUCCESS.md` or ticket templates are created.

## Planning store

Atelier requires `bd` on the PATH. It is used as the local planning store for
epics and changesets, including labels and metadata.

## Command behavior (high level)

- `atelier init`

  - Registers the current repo as a project in the data directory.
  - Writes project config and templates.
  - Optionally prompts for project-wide policy and stores it.

- `atelier plan`

  - Creates epics, tasks, and changesets in the planning store.
  - Suggests and validates a `workspace.root_branch` value.

- `atelier policy`

  - Edits project-wide policy shared by planner/worker agents.

- `atelier work`

  - Selects or claims an epic and its next ready changeset.
  - Ensures the epic worktree exists.
  - Creates/records the changeset branch mapping.

- `atelier edit`

  - Opens the selected workspace worktree in `editor.work`.
  - Prompts for a workspace when none is provided.

- `atelier shell` / `atelier exec`

  - Runs an interactive shell or command in the worktree.

- `atelier config`

  - Prints or updates project configuration.

- `atelier status`

  - Shows project status for epics, hooks, changesets, and queued messages.

- `atelier list`

  - Lists available workspaces (root branches) for the current project.

- `atelier clean`

  - Removes worktrees marked finalized (via publish tooling) or when explicitly
    requested.

- `atelier gc`

  - Cleans up stale hooks, claims, orphaned worktrees, and stale queue claims.
  - Closes channel messages when explicit retention metadata is present.
