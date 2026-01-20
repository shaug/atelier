# Atelier — Specification (v2)

## 1. Purpose

Atelier is a **local, installable CLI tool** that manages **workspace-based
development** for a single project. Each workspace represents one unit of work,
one git branch, and (optionally) one agent coding session.

Atelier exists to eliminate branch switching, reduce cognitive load, and make
agent-assisted development predictable, resumable, and human-interruptible.

Atelier is **tool-agnostic** by design. While it integrates well with Codex, it
does not depend on any specific LLM or editor.

______________________________________________________________________

## 2. Core Concepts

### Project

A project is identified by its **local enlistment path** (resolved absolute
path). There is no separate project ID. Project state is stored under the
Atelier data directory (via `platformdirs`), not inside the user repo.

- A project has **one Atelier configuration** stored in the data directory
- Multiple local checkouts with the same origin map to **different** projects
- Atelier commands resolve the project by reading the repo root path; origin is
  stored only as metadata when available

### Workspace

A workspace is a directory representing one unit of work.

- One workspace → one git branch
- Integration expectations are defined by project branch settings
- One workspace → one agent session (best-effort)
- Workspaces are created and managed by `atelier open`

### Repo

Each workspace contains a `repo/` directory that is a real git repository (clone
of the project repo, checked out on a workspace-specific branch).

______________________________________________________________________

## 3. Filesystem Layout

### Project Directory (Atelier data dir)

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ config.json
      ├─ AGENTS.md
      ├─ PROJECT.md
      ├─ templates/
      │  ├─ AGENTS.md
      │  └─ WORKSPACE.md
      └─ workspaces/
```

Notes:

- `<project-key>` is the enlistment basename plus a short SHA-256 of the full
  enlistment path.
- The data directory is platform-specific (e.g.
  `~/Library/Application Support/atelier`).
- `AGENTS.md` may be a symlink to `templates/AGENTS.md` when possible.

### Workspace

```
workspaces/<workspace-key>/
├─ AGENTS.md
├─ PERSIST.md
├─ BACKGROUND.md (optional)
├─ WORKSPACE.md
├─ config.json
└─ repo/
```

Notes:

- `PROJECT.md` is optional and user-owned.
- `templates/WORKSPACE.md` is created by `atelier init` (or `atelier open` when
  needed).
- `templates/AGENTS.md` is created by `atelier init` (or `atelier open` when
  needed) and stores the canonical `AGENTS.md` content.
- `WORKSPACE.md` is copied into new workspaces from `templates/WORKSPACE.md`.
- `PERSIST.md` is created for every new workspace and is managed by Atelier.
- `BACKGROUND.md` is created only when a workspace is created from an existing
  branch.
- `<workspace-key>` is the normalized branch name plus a short SHA-256 of the
  full workspace ID.
- Branch names may include `/` without creating nested directories under
  `workspaces/`.
- The workspace root name is fixed (`workspaces/`) and not configurable.

______________________________________________________________________

## 4. Project Configuration: `config.json`

`config.json` is **application-owned state** stored in the Atelier data
directory (not the user repo). Humans may inspect it, but it is not intended for
frequent manual editing.

### v2 Schema (JSON)

```json
{
  "project": {
    "enlistment": "/path/to/gumshoe",
    "origin": "github.com/org/gumshoe",
    "repo_url": "git@github.com:org/gumshoe.git"
  },
  "branch": {
    "prefix": "scott/",
    "pr": true,
    "history": "manual"
  },
  "agent": {
    "default": "codex",
    "options": {
      "codex": [
        "--full-auto"
      ],
      "claude": []
    }
  },
  "editor": {
    "default": "cursor",
    "options": {
      "cursor": [
        "-w"
      ],
      "subl": [
        "-w"
      ]
    }
  },
  "atelier": {
    "version": "0.2.0",
    "created_at": "2026-01-15T01:10:00Z"
  }
}
```

### Notes

- `project.enlistment` is the **canonical identity** of the project (resolved
  absolute path to the local enlistment)
- `project.origin` is optional metadata derived from the git remote when
  available; it is not used for identity
- `project.repo_url` is the last-seen clone URL for convenience
- `branch.pr` controls whether integration is expected via pull request (default
  `true`)
- `branch.history` defines expected history shape after integration (default
  `manual`; supported values: `manual`, `squash`, `merge`, `rebase`)
- `agent.options` and `editor.options` are **static argv fragments only**
- No templating, interpolation, or logic is supported in config

______________________________________________________________________

## 5. Project-Level `AGENTS.md`

This file is **fully managed by Atelier** and identical across projects and
workspaces. It points to the other policy and context files to read before
starting work.

### Default Template (v2)

```markdown
# Atelier Agent Contract

This project uses **Atelier**, a workspace-based workflow for agent-assisted development.

## How Work Is Organized

- Work happens in isolated workspaces under the Atelier data directory.
- Each workspace maps to one git branch and includes a `repo/` checkout.
- Workspace intent and success criteria live in `WORKSPACE.md`.

## Required Reading

- `PROJECT.md` (if present) for project-level rules.
- `WORKSPACE.md` (if present) for workspace intent, scope, and completion criteria.
- `PERSIST.md` for how to finish and integrate this work (created for new workspaces).
- `BACKGROUND.md` (if present) for context when a workspace is created from an existing branch.

## Execution Expectations

- Complete the work described in `WORKSPACE.md` **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `WORKSPACE.md` rules take precedence over `PROJECT.md`.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
```

`AGENTS.md` is generated by `atelier init` (or `atelier open` when missing) and
is not intended for manual edits. Atelier may use a symlink to the project-level
template (`templates/AGENTS.md`) when possible, otherwise it copies the file.
Symlinks are best-effort and must fall back safely on platforms where they are
unavailable.

______________________________________________________________________

## 6. Workspace Configuration: `config.json`

This file records workspace identity and provenance.

The workspace branch is the canonical identifier and is used with the project
enlistment path to form the workspace ID.

### v2 Schema

```json
{
  "workspace": {
    "branch": "scott/feat-org-api-keys",
    "branch_pr": true,
    "branch_history": "manual",
    "id": "atelier:/path/to/gumshoe:scott/feat-org-api-keys"
  },
  "atelier": {
    "version": "0.2.0",
    "created_at": "2026-01-15T02:03:00Z"
  }
}
```

______________________________________________________________________

## 7. Workspace `AGENTS.md`

This file is the **standard prologue** for each workspace. It is identical
across projects and workspaces, and it does not include integration strategy.
Integration guidance is in `PERSIST.md`.

### Standard Prologue (v2)

```markdown
# Atelier Agent Contract

This project uses **Atelier**, a workspace-based workflow for agent-assisted development.

## How Work Is Organized

- Work happens in isolated workspaces under the Atelier data directory.
- Each workspace maps to one git branch and includes a `repo/` checkout.
- Workspace intent and success criteria live in `WORKSPACE.md`.

## Required Reading

- `PROJECT.md` (if present) for project-level rules.
- `WORKSPACE.md` (if present) for workspace intent, scope, and completion criteria.
- `PERSIST.md` for how to finish and integrate this work (created for new workspaces).
- `BACKGROUND.md` (if present) for context when a workspace is created from an existing branch.

## Execution Expectations

- Complete the work described in `WORKSPACE.md` **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `WORKSPACE.md` rules take precedence over `PROJECT.md`.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
```

Workspace intent and success criteria live in `WORKSPACE.md`, which is fully
user-owned.

### `PERSIST.md`

`PERSIST.md` is created for every new workspace and is managed by Atelier. It
records the integration strategy derived from workspace settings (`branch.pr`
and `branch.history`). Read it before finishing or integrating work. It also
instructs the user to create a local finalization tag
`atelier/<branch-name>/finalized` on the integration commit; `atelier clean`
uses this tag by default.

### `BACKGROUND.md`

`BACKGROUND.md` is created only when a workspace is opened against an existing
branch. It captures a best-effort snapshot at creation time:

- If a PR exists, include its title/body (via `gh` when available; never fail if
  unavailable).
- Otherwise, list a capped set of commit subjects since the merge-base with the
  default branch.

The file is written once and not updated automatically.

______________________________________________________________________

## 8. Policy Overlays: `PROJECT.md` and `WORKSPACE.md`

These user-owned files define additional agent behavior rules that are
orthogonal to Atelier's core execution protocol. `PROJECT.md` is optional;
`WORKSPACE.md` is created for new workspaces but fully user-owned. `PERSIST.md`
and `BACKGROUND.md` are managed by Atelier and do not participate in policy
precedence.

### `PROJECT.md`

- Location: Atelier project directory (same directory as `config.json`)
- Purpose: define project-level agent policies that apply to all workspaces

### `WORKSPACE.md`

- Location: workspace root (alongside `AGENTS.md` and `config.json`)
- Purpose: define workspace intent, scope, and completion criteria while
  overriding project-level rules when needed
- Suggested sections: Goal, Context, Constraints / Considerations, What "Done"
  Looks Like, Notes

### Precedence

If more than one policy file is present, higher precedence wins:

1. `WORKSPACE.md`
2. `PROJECT.md`
3. `AGENTS.md`

Atelier does not parse or modify these files after creation or copy.

______________________________________________________________________

## 9. CLI Commands (v2)

### `atelier init`

Registers the current enlistment path as an Atelier project.

#### Behavior

- Must be run inside a Git repository
- Resolves the repo enlistment path and creates/updates the project under the
  data dir
- Detects the remote default branch (origin/HEAD) when needed instead of storing
  a static `branch.default`
- Creates `config.json` in the project directory (if missing)
- Creates `templates/AGENTS.md` if missing
- Creates project-level `AGENTS.md` if missing (symlink when possible)
- Creates `PROJECT.md` if missing (comment-only stub)
- Creates `templates/WORKSPACE.md` if missing
- Creates the workspace root directory (`workspaces/`) if missing
- Never modifies existing workspaces
- Never writes files into the user repo

______________________________________________________________________

### `atelier open [workspace-branch]`

Ensures a workspace exists and launches or resumes agent work.

`atelier open` may be run from any directory inside a Git repo.

#### Behavior

1. Locate the git repo root and resolve the enlistment path (and origin when
   available)
2. Resolve or create the Atelier project in the data directory
3. Resolve the workspace branch name and workspace key (branch name plus a short
   hash of the workspace ID)
4. Ensure workspace directory exists under `workspaces/<workspace-key>/`
5. If workspace is new:
   - Generate `config.json`
   - Create workspace `AGENTS.md` (symlink to `templates/AGENTS.md` when
     possible)
   - Create `PERSIST.md`
   - Create `BACKGROUND.md` when the workspace branch already exists
   - Copy `templates/WORKSPACE.md` to `WORKSPACE.md`
   - Open `WORKSPACE.md` in the configured editor (blocking)
6. Existing workspaces are not modified
7. Ensure `repo/` exists:
   - Clone repo if missing
   - If the finalization tag `atelier/<branch-name>/finalized` exists, prompt to
     remove it (continue either way)
   - Checkout default branch
   - Create workspace branch if missing
8. Launch agent:
   - Attempt to resume an existing Codex session by scanning local Codex
     transcripts
   - Otherwise start a new session with an opening prompt containing the
     workspace ID
   - Use `agent.options` and `codex -C <workspace-dir>` for execution

#### Flags

- `--raw` treats the argument as the full branch name (no prefix lookup).
- `--branch-pr <true|false>` overrides `branch.pr` for new workspaces and is
  stored in the workspace config. For existing workspaces, the value must match
  the workspace config or `atelier open` errors.
- `--branch-history <manual|squash|merge|rebase>` overrides `branch.history` for
  new workspaces and is stored in the workspace config. For existing workspaces,
  the value must match the workspace config or `atelier open` errors.

#### Special Case: `atelier open` with no workspace branch

If invoked without a workspace branch, Atelier may “take over” the current
branch only when all of the following are true:

- The current repo is on a **non-default branch**
- The working tree is **clean**
- The branch is **fully pushed** to its upstream

When these conditions are met, the current branch becomes the workspace branch.
Otherwise, `atelier open` fails with a clear error message.

______________________________________________________________________

## 10. Codex Session Resumption (Best-Effort)

Atelier may attempt to resume Codex sessions by:

- Scanning `~/.codex/sessions/**` JSON/JSONL files
- Matching the first user message against:
  ```
  atelier:<project.enlistment>:<workspace.branch>
  ```
- Selecting the most recent match

If resumption fails, a new session is started.

Session resumption is **opportunistic** and must never be required for
correctness.

______________________________________________________________________

## 11. Templates

Atelier ships with internal templates for:

- Canonical `AGENTS.md`
- Workspace `WORKSPACE.md`
- Workspace `PERSIST.md`
- `PROJECT.md` (comment-only stub)

`<project-dir>` refers to the Atelier project directory under the data dir.

`<project-dir>/templates/AGENTS.md` is created for each project and stores the
canonical `AGENTS.md` content. Project- and workspace-level `AGENTS.md` files
may be symlinked to this template when possible; otherwise they are copied.

Templates are **copied** (or symlinked for `AGENTS.md`) and Atelier never
auto-updates existing files.

If a project provides:

```
<project-dir>/templates/WORKSPACE.md
```

that file is copied verbatim into new workspaces as `WORKSPACE.md`.

______________________________________________________________________

## 12. Non-Goals

Atelier does **not**:

- Manage multiple projects globally
- Create or manage GitHub repositories (v2)
- Enforce coding standards
- Track PRs or merges
- Maintain background processes
- Auto-upgrade templates

______________________________________________________________________

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

______________________________________________________________________

## 14. Success Criteria (v2)

Atelier v2 is successful if:

- A user can initialize a project once
- Create multiple workspaces without branch switching
- Resume agent work reliably
- Interrupt and resume work using an editor
- Upgrade Atelier without breaking existing projects
- Multiple local checkouts with the same origin map to different projects
- Deleting the Atelier data directory removes state without touching repos
