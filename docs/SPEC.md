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

## 5. Planning Store

Atelier requires `bd` on the PATH for planning storage. Epics and changesets are
stored as records with metadata, labels, and parent/child relationships.

Epic description fields include:

- `workspace.root_branch` (required)
- `worktree_path` (set after worktree creation)
- `external_tickets` (JSON list of linked external tickets, optional)

## 6. Command Semantics

- `atelier init`: register the current repo and write project config.
- `atelier plan`: create epics and changesets; assign `workspace.root_branch`.
- `atelier policy`: edit project-wide policy for planners/workers.
- `atelier work`: select/claim an epic, pick the next ready changeset, and
  ensure worktree + branch mappings exist.
- `atelier edit`: open the selected worktree in `editor.work`.
- `atelier open`: run a shell or command inside the worktree.
- `atelier config`: view or update project config.
- `atelier status`: show hooks, claims, and changeset status.
- `atelier list`: list available workspaces (root branches).
- `atelier gc`: clean up stale hooks and orphaned worktrees.
