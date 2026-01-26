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
      │  ├─ SUCCESS.md
      │  └─ SUCCESS.ticket.md
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
├─ skills/
│  └─ <skill-name>/SKILL.md
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
- `tickets.provider` controls ticket workflows (`none`, `github`, `linear`).
  `atelier config --prompt` asks for the provider; when it is not `none`, it
  also prompts for optional `tickets.default_project` and
  `tickets.default_namespace` (reserved for providers that need a namespace and
  not used for naming today).
- Workspaces capture a base marker (`workspace.base`) with the default branch
  head SHA at creation time; it is used to detect committed work even after
  squash/rebase workflows and is never auto-updated.
- Workspace skill metadata is stored in `config.sys.json` under `skills`, keyed
  by skill name with version and hash metadata.

## Templates and policy files

- `AGENTS.md` is generated from the project templates; it is the entry point for
  agent instructions inside each workspace.
- `SUCCESS.md` is copied into new workspaces from the project templates.
- `SUCCESS.ticket.md` is an optional ticket-focused template used when
  `atelier open --ticket` creates a new workspace. It supports
  `${ticket-provider}`, `${ticket-id}`, and `${project-name}` placeholders.
- `PERSIST.md` is generated per workspace to describe integration expectations.
- `BACKGROUND.md` is created only when a workspace is created from an existing
  branch.
- Managed template hashes are stored under `atelier.managed_files` to determine
  whether a template is user-modified.
- Upgrade policy (`always`, `ask`, `manual`) controls whether template updates
  are applied automatically, with prompts when needed.

## Agent publish vocabulary

Atelier workspaces use consistent command words in `PERSIST.md`/`AGENTS.md`:

- `publish`: publish only (no finalization/tagging). If `branch.pr` is true,
  commit, push, and create/update the PR. If `branch.pr` is false, commit,
  integrate onto the default branch per the history policy, and push.
- `persist`: save progress without finalizing. If `branch.pr` is true, commit
  and push the workspace branch only (no PR). If `branch.pr` is false, treat it
  the same as `publish`.
- `finalize`: ensure publishing is complete (perform publish if needed), then
  integrate onto the default branch (merge PR or rebase/merge as configured),
  push the default branch, and create the local finalization tag.

## Command behavior

- `atelier init`

  - Registers the current repo as a project in the data directory.
  - Writes project config, templates, and scaffold files.
  - Does not modify the repo itself.

- `atelier open`

  - Resolves a workspace name (prefixed unless `--raw`).
  - Implicit open is allowed only when the current branch is non-default, clean,
    and fully pushed to its upstream.
  - `--ticket` can be repeated (or comma-separated) to attach ticket refs.
  - Ensures project scaffolding and handles template upgrades per policy.
  - Creates workspace metadata and config when missing.
  - Clones the repo into `repo/` if missing, checks out the workspace branch,
    and optionally creates it.
  - Prints a workspace banner (name + path).
  - Prompts to remove an existing finalization tag before reopening.
  - When `--ticket` is supplied, the first ticket reference can drive workspace
    naming when no branch is provided (best-effort GitHub title lookup when
    `tickets.provider=github` and `gh` is available; otherwise prompts for an
    optional title). New workspaces render the ticket template when available,
    append a `## Tickets` section to `SUCCESS.md`, and store refs in the
    workspace config.
  - Opens the workspace policy doc on first creation unless `--no-edit` is set
    (or forced via `--edit`), then resumes or starts the agent session.
  - `--yolo` adds the least-restrictive agent flags for that invocation.
  - Exposes workspace identity via `ATELIER_*` environment variables for editors
    and agents.
  - Applies terminal chrome when supported (WezTerm, Kitty, tmux, iTerm2), with
    iTerm2 setting session titles (OSC 1) and tab/window titles (OSC 2).

- `atelier work` / `atelier shell` / `atelier exec`

  - Resolve an existing workspace repo and open the configured editor or shell.
  - Do not create new workspaces.
  - `--workspace` targets the workspace root instead of `repo/`.
  - `--set-title` emits a terminal title escape (best-effort).
  - `atelier shell --shell` overrides the interactive shell selection.
  - Exposes workspace identity via `ATELIER_*` environment variables.

- `atelier config`

  - Prints merged project config or workspace config when a branch is provided.
  - `--installed`, `--prompt`, `--reset`, and `--edit` operate on user-editable
    defaults (no workspace branch allowed with those flags).

- `atelier template`

  - Prints or edits templates for `project`, `workspace`, or `success` targets.
  - `--ticket` selects the ticket SUCCESS.md template for workspace targets.
  - `--installed` uses the installed template cache; `--edit` opens in
    `editor.edit`.

- `atelier edit`

  - Opens `PROJECT.md` (`--project`) or a workspace `SUCCESS.md` in
    `editor.edit`.

- `atelier describe`

  - With no args, shows project overview plus a workspace summary table.
  - With a workspace name, shows detailed status (clean/dirty, ahead/behind,
    diffstat, last commit).
  - Supports `--finalized`, `--no-finalized`, and `--format=json`.

- `atelier list`

  - Lists known workspaces (names only).

- `atelier clean`

  - Defaults to cleaning finalized workspaces.
  - Uses the finalization tag `atelier/<branch-name>/finalized` in the workspace
    repo or the main enlistment to determine finalization.
  - Remote branch deletion is only allowed for finalized workspaces unless the
    user confirms otherwise.
  - `--dry-run` prints planned deletions without removing anything.
  - `--orphans` removes orphaned workspaces (missing config or repo directory).

- `atelier remove` / `atelier rm`

  - Removes project data from the Atelier data directory.
  - Supports removing a single project, all projects, or orphaned projects.
  - Never touches user repos.

- `atelier upgrade`

  - Applies managed template and config migrations for projects/workspaces.
  - `--installed` refreshes the installed template cache.
  - `--all-projects` targets every project in the data dir.
  - `--no-projects` or `--no-workspaces` restricts what gets upgraded.
  - `--dry-run` shows planned changes; `--yes` applies without confirmation.
  - Prompts before overwriting modified managed files unless `--keep-modified`.

- `atelier template` / `atelier edit`

  - Provide explicit control over template updates and editing of project or
    workspace policy documents.
  - `atelier template --ticket` prints/edits the `SUCCESS.ticket.md` template
    for workspace targets.

## Non-goals

- No background services or daemons.
- No implicit modifications to user repos beyond the workspace checkouts.
- No automatic upgrades of user-owned files without explicit policy.
