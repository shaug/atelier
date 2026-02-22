# Atelier Behavior and Design Notes

This document captures the current behavior of the Atelier CLI. It is a compact
overview; command-specific details live in module docstrings under
`src/atelier/commands`.

See `docs/dogfood.md` for the end-to-end dogfood golden path.

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
- **Changeset**: Executable unit under an epic. It is usually a child bead, but
  guardrail-sized single-unit work may execute directly on the epic labeled
  `at:changeset`.
- **Workspace root branch**: User-facing branch name for the epic. Stored as
  `workspace.root_branch` in epic metadata and labeled
  `workspace:<root_branch>`.
- **Worktree**: A per-epic git worktree checkout stored under the data
  directory. Worktree mappings live under `worktrees/.meta/`.
- **Worktree path**: Stored as `worktree_path` in epic metadata once created.
- **Changeset labels**: Changesets use `cs:planned`, `cs:ready`,
  `cs:in_progress`, `cs:merged`, and `cs:abandoned` to capture non-derivable
  lifecycle state.
  - `cs:ready` means the changeset definition is complete and worker-executable
    when dependencies are satisfied.
  - Dependency/unblock readiness is determined by `bd ready`, not by
    transitioning labels at dependency completion time.
- **External tickets**: Linked via `external_tickets` in bead descriptions with
  provider labels like `ext:github`.

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

Atelier planning always uses a project-scoped Beads store at:

`<atelier-project-dir>/.beads`

Atelier also enforces the Beads issue prefix `at` for this store.

Repository-local Beads stores (for example `<repo>/.beads`) are not used for
Atelier planning state. They are treated as external ticket sources.

## Command behavior (high level)

- `atelier init`

  - Registers the current repo as a project in the data directory.
  - Writes project config and templates.
  - Optionally prompts for project-wide policy and stores it.

- `atelier plan`

  - Creates epics, tasks, and changesets in the planning store.
  - Suggests and validates a `workspace.root_branch` value.
  - Installs a read-only guardrail hook for planner worktrees and warns on dirty
    working trees.
  - Planner sessions can refresh the same read-only startup overview on demand
    via the `planner_startup_check` skill script.

- `atelier policy`

  - Shows project-wide policy shared by planner/worker agents.
  - `--edit` opens policy in `editor.edit`.

- `atelier work`

  - Selects or claims an epic and its next ready changeset.
  - Ensures the epic worktree exists.
  - Creates/records the changeset branch mapping.
  - Uses run mode (`ATELIER_RUN_MODE`) to decide whether to run once, loop while
    work is ready, or watch for new work.

- `atelier daemon`

  - Starts/stops a long-lived worker loop.
  - Starts/stops the bd daemon when full-stack mode is requested.

- `atelier edit`

  - Opens the selected workspace worktree in `editor.work`.
  - Prompts for a workspace when none is provided.

- `atelier open`

  - Runs an interactive shell or command in the worktree.

- `atelier config`

  - Prints or updates project configuration.

- `atelier status`

  - Shows project status for epics, hooks, changesets, and queued messages.

- `atelier list`

  - Lists available workspaces (root branches) for the current project.

- `atelier gc`

  - Cleans up stale hooks, claims, orphaned worktrees, and stale queue claims.
  - Closes channel messages when explicit retention metadata is present.
  - Channel retention metadata can be set via `retention_days` or `expires_at`
    in message frontmatter.
