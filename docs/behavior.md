# Atelier Behavior and Design Notes

This document captures the intended behavior of the Atelier CLI without the full
weight of a formal specification. Module-level docstrings (especially in
`src/atelier/commands`) provide additional, command-specific details.

## Purpose

Atelier is a local, installable CLI for managing workspace-based development in
one Git repo at a time. Each workspace is an isolated unit of work tied to a
single branch and (optionally) an agent session.

Atelier prioritizes explicit intent, predictable filesystem layout, and minimal
side effects inside the user's repo.

## Core concepts

- Project: identified by the absolute path to a local enlistment.
- Workspace: one branch + one workspace directory + one repo checkout.
- Workspace ID: `atelier:<enlistment-path>:<branch>` (stable identifier used for
  naming).
- Data directory: determined via `platformdirs` (user data dir for `atelier`).

## Filesystem layout

Project directory (under the Atelier data dir):

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ config.sys.json
      ├─ config.user.json
      ├─ PROJECT.md
      ├─ templates/
      │  ├─ AGENTS.md
      │  └─ SUCCESS.md
      └─ workspaces/
```

Workspace directory:

```
workspaces/<workspace-key>/
├─ AGENTS.md
├─ PROJECT.md
├─ PERSIST.md
├─ BACKGROUND.md (optional)
├─ SUCCESS.md
├─ config.sys.json
├─ config.user.json
└─ repo/
```

Notes:

- `<project-key>` is derived from the enlistment basename plus a short hash of
  the full enlistment path (legacy origin-based keys are still recognized).
- `<workspace-key>` is derived from the branch name plus a short hash of the
  workspace ID (legacy branch-only keys are still recognized).
- `PROJECT.md` and templates live under the project directory; workspaces get
  copies at creation time.

## Config files

Atelier splits configuration into two JSON files at both the project and
workspace levels:

- `config.sys.json` (system-managed): IDs, timestamps, managed-file hashes, and
  other metadata.
- `config.user.json` (user-managed): branch defaults, agent/editor
  configuration, and upgrade policy.

A merged view is used at runtime. Legacy single-file configs are migrated once
into the split layout.

Additional config notes:

- `git.path` optionally overrides the Git executable (defaults to `git` on
  PATH).
- `project.provider` metadata is optional; when unset, provider integrations are
  skipped.

## Templates and policy files

- `AGENTS.md` is generated from the project templates; it is the entry point for
  agent instructions inside each workspace.
- `SUCCESS.md` is copied into new workspaces from the project templates.
- `PERSIST.md` is generated per workspace to describe integration expectations.
- `BACKGROUND.md` is created only when a workspace is created from an existing
  branch.
- Managed template hashes are stored under `atelier.managed_files` to determine
  whether a template is user-modified.
- Upgrade policy (`always`, `ask`, `manual`) controls whether template updates
  are applied automatically, with prompts when needed.

## Command behavior

- `atelier init`

  - Registers the current repo as a project in the data directory.
  - Writes project config, templates, and scaffold files.
  - Does not modify the repo itself.

- `atelier open`

  - Resolves a workspace name (prefixed unless `--raw`).
  - Implicit open is allowed only when the current branch is non-default, clean,
    and fully pushed to its upstream.
  - Ensures project scaffolding and handles template upgrades per policy.
  - Creates workspace metadata and config when missing.
  - Clones the repo into `repo/` if missing, checks out the workspace branch,
    and optionally creates it.
  - Prompts to remove an existing finalization tag before reopening.
  - Opens the workspace policy doc on first creation, then resumes or starts the
    agent session.

- `atelier work` / `atelier shell` / `atelier exec`

  - Resolve an existing workspace repo and open the configured editor or shell.
  - Do not create new workspaces.

- `atelier list`

  - Lists known workspaces, optionally including status
    (clean/pushed/finalized).

- `atelier clean`

  - Defaults to cleaning finalized workspaces.
  - Uses the finalization tag `atelier/<branch-name>/finalized` in the workspace
    repo or the main enlistment to determine finalization.
  - Remote branch deletion is only allowed for finalized workspaces unless the
    user confirms otherwise.

- `atelier upgrade` / `atelier template` / `atelier edit`

  - Provide explicit control over template updates and editing of project or
    workspace policy documents.

## Non-goals

- No background services or daemons.
- No implicit modifications to user repos beyond the workspace checkouts.
- No automatic upgrades of user-owned files without explicit policy.
