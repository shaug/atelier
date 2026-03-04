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
- **Epic**: Top-level unit of intent that owns a workspace root branch. Epic
  discovery requires `at:epic` as identity/index metadata.
- **Changeset**: Leaf work bead in an epic's progeny graph (any bead without a
  work child whose top-level parent has `at:epic`). If an epic has no children,
  the epic is also a changeset.
- **PR base alignment**: Atelier resolves review PR bases from integration
  lineage rather than raw branch-cut ancestry.
  - Epic-integration PR workflows are unsupported. PR bases must not target
    `changeset.root_branch`.
  - Legacy `changeset.parent_branch == changeset.root_branch` metadata is
    normalized to a non-root integration branch (`workspace.parent_branch` when
    valid, otherwise the project default branch).
  - First reviewable changesets target the integration branch (for example
    `main`).
  - Stacked descendants may target predecessor work branches before predecessor
    integration.
  - After predecessor integration, Atelier restacks descendants onto updated
    lineage and retargets PR base as needed.
  - Repair collapsed lineage metadata with `docs/dependency-lineage-repair.md`.
- **Terminology**: Use `integrate` for getting changes into the main code line.
  Use `merge` only for merge-specific states/actions (for example `git merge` or
  PR merged state).
- **Workspace root branch**: User-facing branch name for the epic. Stored as
  `workspace.root_branch` in epic metadata and labeled
  `workspace:<root_branch>`.
- **Worktree**: A per-epic git worktree checkout stored under the data
  directory. Worktree mappings live under `worktrees/.meta/`.
- **Worktree path**: Stored as `worktree_path` in epic metadata once created.
- **Lifecycle authority**: Execution lifecycle is status-native
  (`deferred|open|in_progress|blocked|closed`) and graph-native (leaf work +
  dependency closure). `cs:*` lifecycle labels are not execution gates.
  `cs:merged` and `cs:abandoned` are used on closed changeset beads to indicate
  resolution/integration status.
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

Agent launch options:

- `agent.options.<agent>` remains supported as the legacy global option map.
- `agent.launch_options.planner.<agent>` and
  `agent.launch_options.worker.<agent>` provide role-scoped overrides.
- No migration is required; existing `agent.options` config continues to work.
- For Claude workers, Atelier defaults to
  `--print --output-format=stream-json --verbose` unless worker-scoped options
  override those flags.

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

Atelier stores a project-scoped Beads issue prefix in project config
(`beads.prefix`). During `atelier init`, Atelier suggests a deterministic prefix
derived from the project name and resolves local collisions deterministically
(for example `ts` -> `ts2`). Migration guidance for existing projects is
documented in `docs/beads-prefix-migration.md`.

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
  - Resumes prior planner sessions by default; `--new-session` forces a fresh
    planner run.
  - Installs a read-only guardrail hook for planner worktrees and warns on dirty
    working trees.
  - Runs deterministic planner teardown on exit: release owned hook/claim state
    and close the session agent bead.
  - Planner sessions can refresh the same read-only startup overview on demand
    via the `planner-startup-check` skill script.
  - Startup overview output is deterministic and template-rendered, including a
    structured fallback section when startup collection fails.

- `atelier policy`

  - Shows project-wide policy shared by planner/worker agents.
  - `--edit` opens policy in `editor.edit`.

- `atelier work`

  - Selects or claims an epic and its next ready changeset.
  - Ensures the epic worktree exists.
  - Creates/records the changeset branch mapping.
  - Uses `--run-mode` to decide whether to run once, loop while work is ready,
    or watch for new work.
  - Runs deterministic worker teardown on exit: release owned hook/claim state
    and close the session agent bead.

- `atelier edit`

  - Opens the selected workspace worktree in `editor.work`.
  - Prompts for a workspace when none is provided.

- `atelier open`

  - Runs an interactive shell or command in the worktree.

- `atelier config`

  - Prints or updates project configuration.

- `atelier status`

  - Shows project status for epics, hooks, changesets, and queued messages.

- `atelier doctor`

  - Reports project health across three check families:
    `prefix_migration_drift`, `startup_blocking_lineage_consistency`, and
    `in_progress_integrity_signals`.
  - Stays read-only in default check mode and does not mutate Beads/worktree
    state.
  - Uses `atelier doctor --fix` as the explicit mutation path.
  - Read-only output reports whether normalization is required as a
    deterministic yes/no with count.
  - Defers `--fix` mutations for active-hook-owned epics unless `--force` is
    provided.
  - Includes rollback guidance based on `bd info --json` plus filesystem backups
    for Beads and mapping metadata.
  - Does not trigger `atelier gc`.

- `atelier list`

  - Lists available workspaces (root branches) for the current project.

- `atelier gc`

  - Cleans up stale hooks, claims, orphaned worktrees, and stale queue claims.
  - Scans the full `at:agent` bead set (`bd list --all --limit 0`) so a single
    pass can release all stale session agents.
  - Closes channel messages when explicit retention metadata is present.
  - Channel retention metadata can be set via `retention_days` or `expires_at`
    in message frontmatter.
