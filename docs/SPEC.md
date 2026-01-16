# Atelier — Specification (v2)

## 1. Purpose

Atelier is a **local, installable CLI tool** that manages **workspace-based development** for a single project. Each workspace represents one unit of work, one git branch, and (optionally) one agent coding session.

Atelier exists to eliminate branch switching, reduce cognitive load, and make agent-assisted development predictable, resumable, and human-interruptible.

Atelier is **tool-agnostic** by design. While it integrates well with Codex, it does not depend on any specific LLM or editor.

---

## 2. Core Concepts

### Project
A project is identified by its **normalized Git origin URL**. There is no separate
project ID. Project state is stored under the Atelier data directory (via
`platformdirs`), not inside the user repo.

- A project has **one Atelier configuration** stored in the data directory
- Multiple local checkouts with the same origin map to the **same** project
- Atelier commands resolve the project by reading the repo's origin

### Workspace
A workspace is a directory representing one unit of work.

- One workspace → one git branch
- Integration expectations are defined by project branch settings
- One workspace → one agent session (best-effort)
- Workspaces are created and managed by `atelier open`

### Repo
Each workspace contains a `repo/` directory that is a real git repository (clone of the project repo, checked out on a workspace-specific branch).

---

## 3. Filesystem Layout

### Project Directory (Atelier data dir)

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ .atelier.json
      ├─ AGENTS.md
      ├─ PROJECT.md
      ├─ templates/
      │  └─ WORKSPACE.md
      └─ workspaces/
```

Notes:

- `<project-key>` is a stable, filesystem-safe key derived from the normalized origin.
- The data directory is platform-specific (e.g. `~/Library/Application Support/atelier`).

### Workspace

```
workspaces/<workspace-name>/
├─ AGENTS.md
├─ WORKSPACE.md
├─ .atelier.workspace.json
└─ repo/
```

Notes:

- `PROJECT.md` is optional and user-owned.
- `templates/WORKSPACE.md` is optional and only created when explicitly opted in.
- `WORKSPACE.md` exists only when copied from `templates/WORKSPACE.md`.
- Workspace names may include `/`, creating nested directories under `workspaces/`.
- The workspace root name is fixed (`workspaces/`) and not configurable.

---

## 4. Project Configuration: `.atelier.json`

`.atelier.json` is **application-owned state** stored in the Atelier data
directory (not the user repo). Humans may inspect it, but it is not intended for
frequent manual editing.

### v2 Schema (JSON)

```json
{
  "project": {
    "name": "gumshoe",
    "origin": "https://github.com/org/gumshoe",
    "repo_url": "git@github.com:org/gumshoe.git"
  },
  "branch": {
    "default": "main",
    "prefix": "scott/",
    "pr": true,
    "history": "manual"
  },
  "agent": {
    "default": "codex",
    "options": {
      "codex": ["--full-auto"],
      "claude": []
    }
  },
  "editor": {
    "default": "cursor",
    "options": {
      "cursor": ["-w"],
      "subl": ["-w"]
    }
  },
  "atelier": {
    "version": "0.2.0",
    "created_at": "2026-01-15T01:10:00Z"
  }
}
```

### Notes

- `project.origin` is the **canonical identity** of the project (normalized origin)
- `project.repo_url` is the last-seen clone URL for convenience; origin identity
  is still based on `project.origin`
- `branch.pr` controls whether integration is expected via pull request (default `true`)
- `branch.history` defines expected history shape after integration
  (default `manual`; supported values: `manual`, `squash`, `merge`, `rebase`)
- `agent.options` and `editor.options` are **static argv fragments only**
- No templating, interpolation, or logic is supported in config

---

## 5. Project-Level `AGENTS.md`

This file describes the **Atelier workflow overlay only**. It does not describe code layout or coding conventions.

### Default Template (v2)

```markdown
# Atelier Project Overlay

This project is managed using **Atelier**, a workspace-based workflow for
agent-assisted development.

## How Work Is Organized

- Development work is performed in isolated **workspaces**
- Workspaces live under the Atelier project directory managed in the local data dir
- Each workspace represents **one unit of work**
- Each workspace has its own `AGENTS.md` defining intent and scope

## Authority

- This file describes only the **Atelier workflow overlay**
- Workspace `AGENTS.md` files define execution expectations
- Repository-specific coding conventions are defined elsewhere
  (e.g. a repository-level `AGENTS.md`, if present)

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in a workspace, read it and apply the rules
defined there as well.

In case of conflict:
- `WORKSPACE.md` rules take precedence over `PROJECT.md`
- `PROJECT.md` rules take precedence over this file

- Atelier project metadata lives in the local data directory (not in the repo).
```

This file is generated by `atelier init`. Users may edit it, but most will not.

---

## 6. Workspace Configuration: `.atelier.workspace.json`

This file records workspace identity and provenance.

### v2 Schema

```json
{
  "workspace": {
    "name": "feat-org-api-keys",
    "branch": "scott/feat-org-api-keys",
    "branch_pr": true,
    "branch_history": "manual",
    "id": "atelier:https://github.com/org/gumshoe:feat-org-api-keys"
  },
  "atelier": {
    "version": "0.2.0",
    "created_at": "2026-01-15T02:03:00Z"
  }
}
```

---

## 7. Workspace `AGENTS.md`

This file is the **execution contract** for agents and humans.

### Structure

1. **Standard prologue** (owned by Atelier)
2. **User-owned intent**, with suggested headers and commented guidance

### Standard Prologue (v2)

```markdown
<!-- atelier:<project.origin>:<workspace.name> -->

# Atelier Workspace

This directory is an **Atelier workspace**.

## Workspace Model

- This workspace represents **one unit of work**
- All code changes for this work should be made under `repo/`
- The code in `repo/` is a real git repository and should be treated normally
- This workspace maps to **one git branch**
- Integration expectations are defined below

## Execution Expectations

- Complete the work described in this file **to completion**
- Do not expand scope beyond what is written here
- Prefer small, reviewable changes over large refactors
- Avoid unrelated cleanup unless explicitly required

## Agent Context

When operating in this workspace:

- Treat this workspace as the **entire world**
- Do not reference or modify other workspaces
- Read the remainder of this file carefully before beginning work

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in this workspace, read it and apply the rules
defined there as well.

In case of conflict:
- `WORKSPACE.md` rules take precedence over `PROJECT.md`
- `PROJECT.md` rules take precedence over this file

## Integration Strategy

This section describes expected coordination and history semantics.
Atelier does not automate integration.

- Pull requests expected: yes
- History policy: manual

When this workspace's success criteria are met:

- The workspace branch is expected to be pushed to the remote.
- A pull request against the default branch is the expected integration mechanism.
- Manual review is assumed; integration should not happen automatically.
- The intended merge style is manual (no specific history behavior is implied).
- Integration should wait for an explicit instruction in the thread.

After reading this file, proceed with the work described below.
```

### Suggested User Sections (commented)

```markdown
---

## Goal

<!-- Describe what this workspace is meant to accomplish. -->

## Context

<!-- Relevant background, links, tickets, or prior discussion. -->

## Constraints / Considerations

<!-- Technical, organizational, or temporal constraints. -->

## What “Done” Looks Like

<!-- Describe how to know when this workspace is complete. -->

## Notes

<!-- Optional execution notes or reminders. -->
```

Users may freely edit, reorder, or delete these sections.

---

## 8. Policy Overlays: `PROJECT.md` and `WORKSPACE.md`

These optional, user-owned files define additional agent behavior rules that
are orthogonal to Atelier's core execution protocol.

### `PROJECT.md`

- Location: Atelier project directory (same directory as `.atelier.json`)
- Purpose: define project-level agent policies that apply to all workspaces

### `WORKSPACE.md`

- Location: workspace root (alongside `AGENTS.md` and `.atelier.workspace.json`)
- Purpose: define workspace-specific policies and override project-level rules

### Precedence

If more than one policy file is present, higher precedence wins:

1. `WORKSPACE.md`
2. `PROJECT.md`
3. `AGENTS.md`

Atelier does not parse or modify these files after creation or copy.

---

## 9. CLI Commands (v2)

### `atelier init`

Registers the current repo origin as an Atelier project.

#### Behavior

- Must be run inside a Git repository with a resolved `origin` remote
- Resolves the repo origin and creates/updates the project under the data dir
- Creates `.atelier.json` in the project directory (if missing)
- Creates project-level `AGENTS.md` if missing
- Creates `PROJECT.md` if missing (comment-only stub)
- Creates the workspace root directory (`workspaces/`) if missing
- Optionally creates `templates/WORKSPACE.md` when explicitly opted in
  (e.g. via `--workspace-template`)
- Never modifies existing workspaces
- Never writes files into the user repo

---

### `atelier open [workspace-name]`

Ensures a workspace exists and launches or resumes agent work.

`atelier open` may be run from any directory inside a Git repo.

#### Behavior

1. Locate the git repo root and resolve the repo origin
2. Resolve or create the Atelier project in the data directory
3. Ensure workspace directory exists
4. If workspace is new:
   - Generate `.atelier.workspace.json`
   - Generate workspace `AGENTS.md` from template
   - Copy `templates/WORKSPACE.md` to `WORKSPACE.md` if present
   - Open `AGENTS.md` in the configured editor (blocking)
5. Ensure `repo/` exists:
   - Clone repo if missing
   - Checkout default branch
   - Create workspace branch if missing
6. Launch agent:
   - Attempt to resume an existing Codex session by scanning local Codex transcripts
   - Otherwise start a new session with an opening prompt containing the workspace ID
   - Use `agent.options` and `codex -C <workspace-dir>` for execution

#### Flags

- `--branch-pr <true|false>` overrides `branch.pr` for new workspaces and is
  stored in the workspace config. For existing workspaces, the value must match
  the workspace config or `atelier open` errors.

#### Special Case: `atelier open` with no workspace name

If invoked without a workspace name, Atelier may “take over” the current branch
only when all of the following are true:

- The current repo is on a **non-default branch**
- The working tree is **clean**
- The branch is **fully pushed** to its upstream

When these conditions are met, the current branch name becomes the workspace
name and the workspace branch. Otherwise, `atelier open` fails with a clear
error message.
- `--branch-history <manual|squash|merge|rebase>` overrides `branch.history` for
  new workspaces and is stored in the workspace config. For existing workspaces,
  the value must match the workspace config or `atelier open` errors.

---

## 10. Codex Session Resumption (Best-Effort)

Atelier may attempt to resume Codex sessions by:

- Scanning `~/.codex/sessions/**` JSON/JSONL files
- Matching the first user message against:
  ```
  atelier:<project.origin>:<workspace.name>
  ```
- Selecting the most recent match

If resumption fails, a new session is started.

Session resumption is **opportunistic** and must never be required for correctness.

---

## 11. Templates

Atelier ships with internal templates for:

- Project `AGENTS.md`
- Workspace `AGENTS.md`
- `PROJECT.md` (comment-only stub)

`<project-dir>` refers to the Atelier project directory under the data dir.

If a project provides:

```
<project-dir>/templates/AGENTS.md
```

that file is used as the **workspace AGENTS.md template** instead of the built-in one.

Templates are **copied, not referenced**. Atelier never auto-updates existing files.

If a project provides:

```
<project-dir>/templates/WORKSPACE.md
```

that file is copied verbatim into new workspaces as `WORKSPACE.md`.

---

## 12. Non-Goals

Atelier does **not**:

- Manage multiple projects globally
- Create or manage GitHub repositories (v2)
- Enforce coding standards
- Track PRs or merges
- Maintain background processes
- Auto-upgrade templates

---

## 13. Implementation Guidelines (v2)

### Language & Runtime

- **Python 3.11+**
- Packaged as an installable CLI
- Installed via `pipx` or equivalent

### Tooling

- Use **`uv`** for:
  - dependency management
  - packaging
  - reproducible builds
- Use standard Python libraries where possible
- Prefer `subprocess` for invoking git, agent, and editor commands

### CLI Framework

- Use a mature CLI framework (e.g. `typer` or `argparse`)
- Commands must be:
  - deterministic
  - safe by default
  - explicit about side effects

### Design Principles

- Filesystem is the source of truth
- No global registries
- No background services
- No hidden state
- Human intent before agent execution

---

## 14. Success Criteria (v2)

Atelier v2 is successful if:

- A user can initialize a project once
- Create multiple workspaces without branch switching
- Resume agent work reliably
- Interrupt and resume work using an editor
- Upgrade Atelier without breaking existing projects
- Multiple local checkouts with the same origin share one project
- Deleting the Atelier data directory removes state without touching repos
