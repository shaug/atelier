# Atelier — Specification (v2)

## 1. Purpose

Atelier is a **local, installable CLI tool** that manages **workspace-based
development** for a single project. Each workspace represents one unit of work,
one git branch, and (optionally) one agent coding session.

Atelier exists to eliminate branch switching, reduce cognitive load, and make
agent-assisted development predictable, resumable, and human-interruptible.

Atelier is **tool-agnostic** by design. While it integrates with Codex and other
supported agent CLIs, it does not depend on any specific LLM or editor.

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
      ├─ config.sys.json
      ├─ config.user.json
      ├─ PROJECT.md
      ├─ templates/
      │  ├─ AGENTS.md
      │  └─ SUCCESS.md
      └─ workspaces/
```

Notes:

- `<project-key>` is the enlistment basename plus a short SHA-256 of the full
  enlistment path.
- The data directory is platform-specific (e.g.
  `~/Library/Application Support/atelier`).

### Workspace

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

- `PROJECT.md` is optional and user-owned in the project directory; it is
  linked/copied into new workspaces as `PROJECT.md`.
- `AGENTS.md` may be a symlink to `templates/AGENTS.md` when possible.
- `templates/SUCCESS.md` is created by `atelier init` (or `atelier open` when
  needed).
- `templates/AGENTS.md` is created by `atelier init` (or `atelier open` when
  needed) and stores the canonical `AGENTS.md` content.
- `SUCCESS.md` is copied into new workspaces from `templates/SUCCESS.md`.
- If `templates/SUCCESS.md` is missing and `templates/WORKSPACE.md` exists
  (legacy), that file is copied into new workspaces as `WORKSPACE.md`.
- `PERSIST.md` is created for every new workspace and is managed by Atelier.
- `BACKGROUND.md` is created only when a workspace is created from an existing
  branch.
- `<workspace-key>` is the normalized branch name plus a short SHA-256 of the
  full workspace ID.
- Branch names may include `/` without creating nested directories under
  `workspaces/`.
- The workspace root name is fixed (`workspaces/`) and not configurable.

______________________________________________________________________

## 4. Project Configuration: `config.sys.json` + `config.user.json`

Atelier stores configuration across two files in the project directory:

- `config.sys.json` is system-managed (IDs, origin, timestamps, managed hashes).
- `config.user.json` is user-managed (branch defaults, agent, editor roles,
  upgrade policy).

Runtime configuration is the merged view of both files. Legacy `config.json`
files are migrated once into the split layout, with a `config.json.bak` backup
left behind.

### v2 Schema (Merged JSON)

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
    "default": "agent-name",
    "options": {
      "agent-name": [
        "--full-auto"
      ]
    }
  },
  "editor": {
    "edit": [
      "subl",
      "-w"
    ],
    "work": [
      "code"
    ]
  },
  "atelier": {
    "version": "0.2.0",
    "created_at": "2026-01-15T01:10:00Z",
    "upgrade": "ask"
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
- `atelier.upgrade` controls when managed templates are upgraded (default `ask`;
  supported values: `always`, `ask`, `manual`)
- `editor.edit` should be a blocking command (e.g., `-w`)
- `editor.work` should be non-blocking by default (omit `-w`)
- `agent.options` are **static argv fragments only**
- `editor.edit` and `editor.work` are **argv lists** (command + args)
- No templating, interpolation, or logic is supported in config
- Agent CLIs are assumed to be installed and authenticated by the user
- Atelier validates that the configured agent is available on PATH (using
  `--version` when possible)

### Supported agent CLIs (install links)

- [Codex CLI](https://developers.openai.com/codex/cli/)
- [Claude Code CLI](https://claude.com/product/claude-code)
- [Gemini CLI](https://geminicli.com)
- [GitHub Copilot CLI](https://github.com/features/copilot/cli)
- [Aider](https://aider.chat/docs/install.html)

______________________________________________________________________

## 5. `AGENTS.md` (Workspace)

Atelier creates a single `AGENTS.md` per workspace. There is no project-level
`AGENTS.md`. This file is **fully managed by Atelier** and identical across
projects and workspaces. It points to the other policy and context files to read
before starting work.

### Default Template (v2)

```markdown
# Atelier Agent Contract

This project uses **Atelier**, a workspace-based workflow for agent-assisted development.

## How Work Is Organized

- Work happens in isolated workspaces under the Atelier data directory.
- Each workspace maps to one git branch and includes a `repo/` checkout.
- Workspace intent and success criteria live in `SUCCESS.md` (or
  `WORKSPACE.md` for legacy workspaces).
- All Atelier policy files for this workspace live alongside this file.

## Required Reading

- `PROJECT.md` (if present) for project-wide rules; it is linked/copied into
  this workspace.
- `SUCCESS.md` (or `WORKSPACE.md` for legacy workspaces) for workspace intent, scope, and completion criteria.
- `PERSIST.md` for how to finish and integrate this work (created for new workspaces).
- `BACKGROUND.md` (if present) for context when a workspace is created from an existing branch.

## Execution Expectations

- Complete the work described in `SUCCESS.md` (or `WORKSPACE.md` for legacy workspaces) **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.

Ensure the configured agent CLI is installed and authenticated
(see `agent.default`).

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `SUCCESS.md` rules take precedence over `PROJECT.md`.
- For legacy workspaces, `WORKSPACE.md` is treated as equivalent.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
```

`AGENTS.md` is generated by `atelier open` when missing and is not intended for
manual edits. Atelier may use a symlink to the project template
(`templates/AGENTS.md`) when possible, otherwise it copies the file. Symlinks
are best-effort and must fall back safely on platforms where they are
unavailable.

______________________________________________________________________

## 6. Workspace Configuration: `config.sys.json` + `config.user.json`

These files record workspace identity and provenance. The merged view is used at
runtime.

The workspace branch is the canonical identifier and is used with the project
enlistment path to form the workspace ID.

### v2 Schema (Merged)

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
    "created_at": "2026-01-15T02:03:00Z",
    "upgrade": "ask"
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
- Workspace intent and success criteria live in `SUCCESS.md` (or
  `WORKSPACE.md` for legacy workspaces).
- All Atelier policy files for this workspace live alongside this file.

## Required Reading

- `PROJECT.md` (if present) for project-wide rules; it is linked/copied into this
  workspace.
- `SUCCESS.md` (or `WORKSPACE.md` for legacy workspaces) for workspace intent, scope, and completion criteria.
- `PERSIST.md` for how to finish and integrate this work (created for new workspaces).
- `BACKGROUND.md` (if present) for context when a workspace is created from an existing branch.

## Execution Expectations

- Complete the work described in `SUCCESS.md` (or `WORKSPACE.md` for legacy workspaces) **to completion**.
- Do not expand scope beyond what is written there.
- Prefer small, reviewable changes over large refactors.
- Avoid unrelated cleanup unless explicitly required.

## Agent Context

- When operating in a workspace, treat it as the entire world.
- Do not reference or modify other workspaces.

## Policy Precedence

- `SUCCESS.md` rules take precedence over `PROJECT.md`.
- For legacy workspaces, `WORKSPACE.md` is treated as equivalent.
- `PROJECT.md` rules take precedence over this file.

Before finalizing work in a workspace, read `PERSIST.md`.

After reading the applicable files, proceed with the work described there.
```

Workspace intent and success criteria live in `SUCCESS.md`, which is fully
user-owned. Legacy workspaces may still use `WORKSPACE.md`.

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

## 8. Policy Overlays: `PROJECT.md` and `SUCCESS.md`

These user-owned files define additional agent behavior rules that are
orthogonal to Atelier's core execution protocol. `PROJECT.md` is optional;
`SUCCESS.md` is created for new workspaces but fully user-owned. `WORKSPACE.md`
is legacy and treated as equivalent when present. `PERSIST.md` and
`BACKGROUND.md` are managed by Atelier and do not participate in policy
precedence.

### `PROJECT.md`

- Location: Atelier project directory (same directory as `config.sys.json`);
  linked/copied into each workspace root as `PROJECT.md` when the workspace is
  created.
- Purpose: define project-level agent policies that apply to all workspaces

### `SUCCESS.md`

- Location: workspace root (alongside `AGENTS.md` and `config.sys.json`)
- Purpose: define workspace intent, scope, success criteria, and verification
  while overriding project-level rules when needed
- Suggested sections: Goal, Context, Constraints / Considerations, Success
  Criteria, Verification, Notes

### Precedence

If more than one policy file is present, higher precedence wins:

1. `SUCCESS.md` (or legacy `WORKSPACE.md`)
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
- Creates `config.sys.json` and `config.user.json` in the project directory (if
  missing)
- Creates `templates/AGENTS.md` if missing
- Creates `PROJECT.md` if missing (comment-only stub)
- Creates `templates/SUCCESS.md` if missing (leaves legacy
  `templates/WORKSPACE.md` untouched)
- Creates the workspace root directory (`workspaces/`) if missing
- Never modifies existing workspaces
- Never writes files into the user repo
- Prompts only for missing config values; subsequent runs are no-ops unless new
  config fields are introduced or explicit overrides are provided

______________________________________________________________________

### `atelier config [workspace-branch]`

Inspect or update Atelier configuration.

#### Behavior

- Must be run inside a Git repository
- Without arguments, prints the merged project config
- With a workspace branch, prints the workspace config
- `--installed` shows or updates installed defaults for user-editable settings
  (`branch`, `agent`, `editor.edit`, `editor.work`, `atelier.upgrade`)
- `--prompt` interactively updates user-editable settings
- `--reset` resets user-editable settings to installed defaults (with
  confirmation)
- Installed defaults are stored at `<atelier-data-dir>/config.user.json` and
  contain only the user-editable sections
- `--edit` opens a temp file containing the user config and writes only when
  valid
- `--edit` cannot be combined with `--prompt`
- Workspace config output cannot be combined with `--installed`, `--prompt`,
  `--reset`, or `--edit`

______________________________________________________________________

### `atelier template <project|workspace|success>`

Print or edit the templates used to seed new documents.

#### Behavior

- Must be run inside a Git repository
- `project` resolves the `PROJECT.md` template
- `workspace`/`success` resolves the `SUCCESS.md` template
- Resolution order: project template → installed cache → built-in default
- `--installed` bypasses the project template (redundant for `project`)
- `--edit` opens the resolved template in `editor.edit`, creating the file when
  missing

______________________________________________________________________

### `atelier edit [workspace-branch]`

Open editable policy documents in `editor.edit`.

#### Behavior

- `atelier edit --project` opens `PROJECT.md`
- `atelier edit <workspace>` opens `SUCCESS.md` (or legacy `WORKSPACE.md`)
- Creates the target file from templates when missing
- `PERSIST.md` and `BACKGROUND.md` are not editable through this command

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
   - Generate `config.sys.json` and `config.user.json`
   - Create workspace `AGENTS.md` (symlink to `templates/AGENTS.md` when
     possible)
   - Create workspace `PROJECT.md` by linking/copying the project-level
     `PROJECT.md`
   - Create `PERSIST.md`
   - Create `BACKGROUND.md` when the workspace branch already exists
   - Copy `templates/SUCCESS.md` to `SUCCESS.md` when available
   - Otherwise copy legacy `templates/WORKSPACE.md` to `WORKSPACE.md`
   - Open the chosen file in `editor.edit` (blocking)
6. Existing workspaces are not modified
7. Ensure `repo/` exists:
   - Clone repo if missing
   - If the finalization tag `atelier/<branch-name>/finalized` exists, prompt to
     remove it (continue either way)
   - Checkout default branch
   - Create workspace branch if missing
8. Launch agent:
   - Attempt to resume an existing session when supported (Codex uses local
     session transcripts; Claude uses `--continue`; Gemini uses `--resume`;
     Copilot uses `--continue`; others start fresh)
   - Otherwise start a new session; only Codex receives an opening prompt
     containing the workspace ID (used for session discovery). Other agents
     start without an opening prompt (Aider avoids it because `--message` exits
     after sending one message).
   - Use `agent.options` and the agent command for execution
   - Codex runs with `--cd <workspace-dir>`; other agents run with the workspace
     as the current working directory
9. Optionally apply terminal chrome (best-effort, decorative only):
   - Detect WezTerm via `WEZTERM_PANE_ID` (or `WEZTERM_PANE`), Kitty via
     `KITTY_WINDOW_ID`, or tmux via `TMUX`
   - Set the active pane title to a workspace label (repo name + branch)
   - Failure or missing capabilities must never affect correctness

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

### `atelier work <workspace-branch>`

Open the workspace repo in the configured work editor.

#### Behavior

- Must be run inside a Git repository
- Resolves the workspace using the project branch prefix (like `atelier open`)
- Errors if the workspace does not exist
- Opens `<workspace>/repo` using `editor.work`
- Does not block the CLI process

______________________________________________________________________

### `atelier shell <workspace-branch> [--] [command ...]`

Open a shell in the workspace repo or run a command there.

#### Behavior

- Must be run inside a Git repository
- Resolves the workspace using the project branch prefix (like `atelier open`)
- Errors if the workspace does not exist
- Runs commands in `<workspace>/repo`
- Never creates or modifies workspaces
- When no command is provided, launches an interactive shell in
  `<workspace>/repo` and exits with the shell's status code
- Shell selection for interactive mode:
  - Prefer a detection library when available (e.g., `shellingham`)
  - Fallback to `$SHELL` on POSIX or `%COMSPEC%` on Windows
  - Final fallback: `bash`/`sh` on POSIX, `cmd.exe` on Windows
- `--shell <path|name>` overrides interactive shell selection only

______________________________________________________________________

### `atelier exec <workspace-branch> [--] [command ...]`

Run a command in the workspace repo.

#### Behavior

- Alias for `atelier shell` command-execution mode
- Requires a command; errors if none is provided
- Runs the command directly (no shell wrapping) in `<workspace>/repo`

______________________________________________________________________

## 10. Agent Session Resumption (Best-Effort)

Atelier may attempt to resume sessions by:

- Codex: scanning `~/.codex/sessions/**` JSON/JSONL files, matching the first
  user message against:
  ```
  atelier:<project.enlistment>:<workspace.branch>
  ```
  and selecting the most recent match.
- Claude: invoking `claude --continue`, which loads the most recent conversation
  in the current directory (no session discovery).
- Gemini: invoking `gemini --resume`, which resumes the most recent conversation
  in the current directory when supported.
- Copilot: invoking `copilot --continue`, which resumes the most recent session
  in the current directory when supported (`copilot --resume` can be used
  manually to select another session).
- Aider: invoking `aider --restore-chat-history` when the chat history file is
  present (`.aider.chat.history.md` by default or `AIDER_CHAT_HISTORY_FILE` when
  set). If no history file is found, start a new session.

Other agents start new sessions because session discovery is not yet supported.

If resumption fails, a new session is started.

Resumption is per-agent; Atelier does not attempt to reuse sessions across
different agent CLIs.

Session resumption is **opportunistic** and must never be required for
correctness.

______________________________________________________________________

## 11. Templates

Atelier ships with internal templates for:

- Canonical `AGENTS.md`
- Workspace `SUCCESS.md`
- Legacy workspace `WORKSPACE.md`
- Workspace `PERSIST.md`
- `PROJECT.md` (comment-only stub)

`<project-dir>` refers to the Atelier project directory under the data dir.

`<project-dir>/templates/AGENTS.md` is created for each project and stores the
canonical `AGENTS.md` content. Workspace `AGENTS.md` files may be symlinked to
this template when possible; otherwise they are copied.

Templates are **copied** (or symlinked for `AGENTS.md`) and Atelier never
auto-updates existing files without an explicit policy.

### Template upgrade policy (`atelier.upgrade`)

`atelier.open` checks for template upgrades only when the stored
`atelier.version` differs from the installed version. Behavior is controlled by
`atelier.upgrade` (project and workspace):

- `manual`: never check or apply upgrades on `open` (use `atelier upgrade`)
- `ask`: show a per-file diff and prompt before applying each change
- `always`: automatically upgrade unmodified managed files; skip modified files
  with a warning and a suggested manual upgrade command

New projects default to `ask`. New workspaces inherit the project policy unless
explicitly set.

If a project provides `templates/SUCCESS.md`, that file is copied verbatim into
new workspaces as `SUCCESS.md`. If `templates/SUCCESS.md` is missing and the
legacy `templates/WORKSPACE.md` exists, that file is copied verbatim into new
workspaces as `WORKSPACE.md`.

______________________________________________________________________

## 12. Non-Goals

Atelier does **not**:

- Manage multiple projects globally
- Create or manage GitHub repositories (v2)
- Enforce coding standards
- Track PRs or merges
- Maintain background processes
- Auto-upgrade templates outside the configured `atelier.upgrade` policy

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
- Dependencies that improve CLI UX (e.g., prompt libraries) are acceptable
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
