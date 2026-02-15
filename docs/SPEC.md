# Atelier — Specification

This document defines the current behavior of the Atelier CLI. It focuses on the
workspace/worktree model, epic planning, and deterministic command behavior.

## 1. Purpose

Atelier is a local, installable CLI that manages workspace-based development
inside a single Git repo at a time. Each workspace is a unit of work with its
own worktree checkout and changeset branches.

## 2. Core Concepts

### Project

A project is identified by its local enlistment path (resolved absolute path).
Project state is stored under the Atelier data directory, not inside the user
repo.

### Epic

An epic is a top-level unit of intent. It owns the workspace root branch and a
worktree checkout.

### Workspace Root Branch

The workspace root branch is the user-facing branch name for an epic. It is
stored in epic metadata as `workspace.root_branch` and labeled
`workspace:<root_branch>`.

### Changeset

A changeset is a planned unit of work under an epic. Each changeset maps to a
branch derived from the root branch:

```
<root_branch>-<changeset_id>
```

Changesets track lifecycle intent using labels:

- `cs:planned`, `cs:ready`, `cs:in_progress`, `cs:merged`, `cs:abandoned`

### Worktree

A worktree is a per-epic Git checkout stored under the Atelier data directory.
Worktree mappings are stored under `worktrees/.meta/`.

## 3. Filesystem Layout

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

Worktree mapping schema (`worktrees/.meta/<epic-id>.json`):

```
{
  "epic_id": "<epic-id>",
  "worktree_path": "worktrees/<epic-id>",
  "root_branch": "<root-branch>",
  "changesets": {
    "<changeset-id>": "<root_branch>-<changeset_id>"
  }
}
```

## 4. Configuration

Atelier uses two JSON files for project configuration:

- `config.sys.json` (system-managed)
- `config.user.json` (user-managed)

Key fields include:

- `branch.prefix`: default prefix for root branches
- `agent.default`: default agent CLI
- `editor.edit`: blocking editor for quick edits
- `editor.work`: non-blocking editor for worktree opens

Agent sessions inherit identity env vars:

- `ATELIER_AGENT_ID`
- `BD_ACTOR`
- `BEADS_AGENT_NAME`

Planner template variables:

- `agent_id`
- `project_root`
- `repo_root`
- `project_data_dir`
- `beads_dir`
- `beads_prefix`
- `planner_worktree`
- `default_branch`
- `external_providers` (comma-separated slugs, or `none`)

## 5. Planning Store

Atelier requires `bd` on the PATH for planning storage. Epics and changesets are
stored as records with metadata, labels, and parent/child relationships.

Atelier planning state is always stored in the project-scoped Beads directory
(`<atelier-project-dir>/.beads`). Repository-local Beads stores are treated as
external systems, not as the source of Atelier planning state. The issue prefix
for this store is `at`.

External ticket linkage and sync semantics are defined in:

- `/Users/scott/code/atelier/docs/SPEC-external-ticket-integration.md`

Epic description fields include:

- `workspace.root_branch` (required)
- `workspace.parent_branch` (integration target, optional)
- `workspace.primary_head` (last known root SHA, optional)
- `workspace.worktree_path` (set after worktree creation)
- `workspace.pr_strategy` (sequential/on-ready/parallel, optional; planned, not
  yet enforced)
- `external_tickets` (JSON list of linked external tickets, optional)

Changeset description fields include:

- `changeset.root_branch` (epic root branch)
- `changeset.parent_branch` (branch this changeset was cut from)
- `changeset.work_branch` (active work branch)
- `changeset.root_base` (root SHA at claim time, optional)
- `changeset.parent_base` (parent SHA at claim time, optional)
- `changeset.integrated_sha` (root SHA after integration, optional)
- `changeset.pr_number` (PR/MR number, optional)
- `changeset.pr_state` (draft|open|approved|merged|closed, optional)

## 6. Command Semantics

- `atelier init`: register the current repo and write project config.
- `atelier plan`: create epics and changesets; assign `workspace.root_branch`.
- `atelier policy`: edit project-wide policy for planners/workers.
- `atelier work`: select/claim an epic, pick the next ready changeset, and
  ensure worktree + branch mappings exist. Run mode controls whether it runs
  once, loops while work is ready, or watches for new work.
- `atelier daemon`: start/stop/status a long-lived worker loop and the bd daemon
  for full-stack mode.
- `atelier edit`: open the selected worktree in `editor.work`.
- `atelier open`: run a shell or command inside the worktree.
- `atelier config`: view or update project config.
- `atelier status`: show hooks, claims, and changeset status.
- `atelier list`: list available workspaces (root branches).
- `atelier gc`: clean up stale hooks and orphaned worktrees.

Worker modes:

- `ATELIER_MODE=prompt|auto` controls epic selection.
- `ATELIER_RUN_MODE=once|default|watch` controls session looping.
- `ATELIER_WATCH_INTERVAL=<seconds>` controls watch polling cadence.
