# Atelier

Atelier is an installable CLI for workspace-based, agent-assisted development
inside local Git repos. It turns each unit of work into its own workspace with a
dedicated git worktree, explicit intent, and a predictable launch path for
agents and humans. Atelier is Git-first by design; provider integrations are
optional and best-effort.

Atelier can manage multiple projects on one machine; each project is identified
by its local enlistment path and stored under the Atelier data directory.

The goal is to simulate web-based agent development on a local machine: you can
hand off and resume workspaces easily, take the wheel at any time, and
coordinate multiple agents across parallel tasks without losing context.

Atelier is:

- a per-repo tool, not a global project manager
- a workspace-first workflow, not a branch-switching helper
- a convention with sharp edges, not a flexible framework

Provider integrations are intentionally minimal: GitHub gets the best support,
and other providers are best-effort when `project.provider` metadata is set.

## Inspiration

Atelier is inspired by the ideas explored in
[*Shipping at Inference Speed*](https://steipete.me/posts/2025/shipping-at-inference-speed),
which argues that many traditional Git workflows introduce unnecessary cognitive
overhead when working with fast, capable coding agents.

In particular, the essay highlights the value of:

- minimizing mental context switches
- evolving codebases linearly when coordination cost is low
- treating LLMs as collaborators, not batch tools

Atelier adopts these ideas where they help, while still supporting branch- and
review-based workflows when coordination and safety matter. It's an adaptation
of the essay's philosophy, not a clone.

Read more in [docs/inspiration.md](docs/inspiration.md).

## Why “atelier”?

*Atelier* (pronounced **ah-tuh-lee-AY**) is the French word for a workshop.

The name reflects how this tool is intended to be used: as a place where work is
shaped iteratively, with humans and tools collaborating closely.

Atelier is not a factory pipeline or a fully automated system. It favors
explicit intent, interruption, and hands-on control over invisible automation.

Agents are collaborators, not background jobs—and the human is always allowed to
step back in and take the reins.

The name is meant to signal craft and collaboration, not art, magic, or opacity.

Read more in [docs/atelier-name.md](docs/atelier-name.md).

## Core Ideas

- One workspace = one unit of work = one branch
- Intent is captured before code (epic planning)
- Workspaces are isolated worktrees with their own git checkout
- Projects are identified by their local enlistment path (each repo you
  initialize is a separate project), not Git origin
- The filesystem is the source of truth

## Behavior and Design Notes

See [docs/behavior.md](docs/behavior.md) for the compact behavioral overview.
Command-specific details live in module docstrings under `src/atelier/commands`.

## Requirements

- Git (for worktrees and branch operations)
- `bd` on your PATH (Atelier's local planning store)

## Agent Setup

Atelier launches the agent CLI configured in `agent.default`. Install and
authenticate the agent CLI you want to use and set `agent.default` accordingly.
Atelier validates that the configured agent is available on your PATH (using
`--version` when possible) and exits early if no agent CLI is available.

### Supported agents

- [Codex CLI](https://developers.openai.com/codex/cli/)
- [Claude Code CLI](https://claude.com/product/claude-code)
- [Gemini CLI](https://geminicli.com)
- [GitHub Copilot CLI](https://github.com/features/copilot/cli)
- [Aider](https://aider.chat/docs/install.html)

### Supported agent features

- Launch agents from the workspace directory
- Best-effort session resumption when the agent CLI supports it
- Opening prompt containing the workspace ID (Codex only)

## Workspace identity environment variables

Atelier sets these environment variables when launching editors, shells, and
agents:

- `ATELIER_WORKSPACE`: workspace branch name
- `ATELIER_PROJECT`: project enlistment path (repo root)
- `ATELIER_WORKSPACE_DIR`: workspace root directory

Example shell prompt (bash/zsh):

```sh
PS1='${ATELIER_WORKSPACE:+[${ATELIER_WORKSPACE}] }\\w$ '
```

Example editor title (VS Code settings):

```json
{
  "terminal.integrated.title": "${env:ATELIER_WORKSPACE} - ${env:ATELIER_PROJECT}"
}
```

## What the CLI Manages

Atelier is intentionally small. The CLI:

- registers a local enlistment as a project in the Atelier data directory
- creates per-epic worktrees under the data directory
- maintains minimal `config.sys.json`/`config.user.json` state for projects
- stores optional project-wide policy for agents
- bootstraps policy/context files (`AGENTS.md`) and installs workspace skills
- tracks changeset branch mappings for each workspace
- launches your editor and shells in a predictable way

## Project Layout

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ config.sys.json
      ├─ config.user.json
      ├─ templates/
      │  ├─ AGENTS.md
      └─ worktrees/
         ├─ .meta/
         │  └─ <epic-id>.json
         └─ <epic-id>/
            └─ <git worktree checkout>
```

Notes:

- `<project-key>` is the enlistment basename plus a short SHA-256 of the full
  enlistment path.
- Worktrees are keyed by epic id; mappings live in `worktrees/.meta/`.

## Quick Start

Create a brand-new local project:

```sh
atelier new [path]
```

If `path` is omitted, the current directory must be empty.

Initialize a project:

```sh
atelier init
```

Run this inside an existing Git repo; Atelier stores state in the data directory
and does not write files into the repo.

You can run `atelier init` in multiple repos; each enlistment becomes its own
project entry.

Start a worker session (select epic + next changeset):

```sh
atelier work
atelier work at-epic123
atelier work --mode auto
```

`atelier work` will:

- claim or select the epic to work on
- pick the next ready changeset
- ensure the worktree and changeset branch mapping exist

Plan epics and changesets:

```sh
atelier plan
atelier plan --create-epic
```

Open a workspace worktree in your editor:

```sh
atelier edit <workspace-branch>
atelier edit <workspace-branch> --workspace
```

Open a shell in a workspace worktree (or run a command there):

```sh
atelier shell <workspace-branch>
atelier shell <workspace-branch> -- python -m http.server
atelier exec <workspace-branch> -- python -m http.server
atelier shell <workspace-branch> --workspace
```

Describe project/workspaces:

```sh
atelier describe
atelier describe --finalized
atelier describe <workspace-branch>
atelier describe <workspace-branch> --format=json
```

List workspaces:

```sh
atelier list
```

Clean completed workspaces (finalization tag):

```sh
atelier clean
```

Remove orphaned workspaces (missing config or repo):

```sh
atelier clean --orphans
```

Delete specific workspaces and keep their branches:

```sh
atelier clean --no-branch feat/login refactor/api
```

Delete everything without prompting:

```sh
atelier clean --all --yes
```

## Notes

- Template upgrades are governed by `atelier.upgrade` (`always`, `ask`,
  `manual`).
- The epic record is the execution contract for each workspace.
- `AGENTS.md` is a managed prologue used to configure agents.
- `atelier policy` edits the project-wide policy shared by planning and work
  agents.
- The `publish` skill records integration guidance derived from workspace config
  and the finalization tag (`atelier/<branch-name>/finalized`) used by
  `atelier clean`.
- Configuration lives in `config.sys.json`/`config.user.json` under the Atelier
  data directory.
- Worktrees live under the data directory and are keyed by epic id.

## CLI Reference

### `atelier --help` and `atelier --version`

Use `atelier --help` to view all commands and options. Use `atelier --version`
to print the installed version and exit.

### `atelier new [path]`

Create a new local Git repo, register it as an Atelier project, and open the
first workspace on the default branch.

Usage:

```sh
atelier new [path]
```

Options:

- `--branch-prefix`: Prefix for workspace branches (e.g., `scott/`).
- `--branch-pr`: Whether workspace branches require pull requests.
- `--branch-history`: History policy (`manual`, `squash`, `merge`, `rebase`).
- `--agent`: Agent name.
- `--editor-edit`: Editor command for blocking edits (e.g., `subl -w`).
- `--editor-work`: Editor command for opening the repo (e.g., `code`).

Example:

```sh
atelier new ~/code/greenfield
```

### `atelier init`

Register the current Git repo as an Atelier project. This command writes
configuration into the Atelier data directory and never modifies the repo.

Usage:

```sh
atelier init
```

Options:

- `--branch-prefix`: Prefix for workspace branches (e.g., `scott/`).
- `--branch-pr`: Whether workspace branches require pull requests.
- `--branch-history`: History policy (`manual`, `squash`, `merge`, `rebase`).
- `--agent`: Agent name.
- `--editor-edit`: Editor command for blocking edits (e.g., `subl -w`).
- `--editor-work`: Editor command for opening the repo (e.g., `code`).

Example:

```sh
atelier init --branch-prefix scott/ --branch-pr false --branch-history rebase
```

### `atelier config [workspace-branch]`

Inspect or update configuration. Without arguments, prints the merged project
config. With a workspace branch, prints that workspace config.

Usage:

```sh
atelier config
atelier config scott/feat/new-search
```

Options:

- `--installed`: Operate on installed defaults instead of the current project.
- `--prompt`: Prompt for user-editable settings (branch/agent/editor roles).
- `--reset`: Reset user-editable settings to installed defaults.
- `--edit`: Edit user config in `editor.edit`.

Examples:

```sh
atelier config --prompt
atelier config --reset
atelier config --installed --prompt
```

### `atelier template agents`

Print or edit templates used to seed new documents.

Usage:

```sh
atelier template agents
```

Options:

- `--installed`: Use the installed template cache.
- `--edit`: Open the resolved template in `editor.edit`.

Examples:

```sh
atelier template agents --edit
atelier template agents --installed
```

### `atelier policy`

Edit project-wide agent policy.

Usage:

```sh
atelier policy
```

Options:

- `--role`: Select policy role (`planner`, `worker`, or `both`).

### `atelier edit <workspace-branch>`

Open the workspace repo in the configured work editor.

Usage:

```sh
atelier edit feat/new-search
```

Options:

- `--raw`: Treat the argument as the full branch name (no prefix lookup).
- `--workspace`: Open the worktree root instead of the default repo path.
- `--set-title`: Emit a terminal title escape (best-effort).

### `atelier work [epic-id]`

Start a worker session for the next ready changeset. If no epic id is provided,
Atelier selects one based on `--mode` (prompt or auto).

Usage:

```sh
atelier work
atelier work at-epic123
atelier work --mode auto
```

Options:

- `--mode`: Worker selection mode (`prompt` or `auto`).

### `atelier plan`

Start a planner session for epics.

Usage:

```sh
atelier plan
atelier plan --create-epic
```

Options:

- `--create-epic`: Open an interactive form to create a new epic.
- `--epic-id`: Plan against an existing epic id.

### `atelier shell <workspace-branch> [--] [command ...]`

Open a shell in a workspace worktree, or run a command there. Use `--shell` to
override the interactive shell selection. Use `--workspace` to run in the
worktree root instead of the default repo path.

Options:

- `--shell`: Shell path or name for interactive mode.
- `--workspace`: Run in the worktree root instead of the default repo path.
- `--set-title`: Emit a terminal title escape.

### `atelier exec <workspace-branch> [--] [command ...]`

Run a command in a workspace worktree. This is an alias for `atelier shell` in
command-execution mode and requires a command. Use `--workspace` to run in the
worktree root instead of the default repo path.

Options:

- `--workspace`: Run in the worktree root instead of the default repo path.
- `--set-title`: Emit a terminal title escape.

### `atelier describe [workspace-branch]`

Show project overview or detailed workspace status. With no workspace argument,
prints a project overview plus a workspace summary table. When a workspace is
provided, includes clean/dirty, ahead/behind, diffstat, and last commit details.

Usage:

```sh
atelier describe
atelier describe --finalized
atelier describe <workspace-branch>
atelier describe <workspace-branch> --format=json
```

Options:

- `--finalized`: Show only finalized workspaces in the project summary.
- `--no-finalized`: Exclude finalized workspaces from the project summary.
- `--format=json`: Emit deterministic JSON output.

### `atelier list`

List workspaces for the current project (names only).

Usage:

```sh
atelier list
```

### `atelier clean`

Delete workspaces safely. By default, this removes only workspaces that have the
local finalization tag `atelier/<branch-name>/finalized`. Remote branches are
deleted only for finalized workspaces; `--all` can target unfinalized ones but
still asks for explicit confirmation before deleting their remote branches.

Usage:

```sh
atelier clean
atelier clean feat/old-branch refactor/api
```

Options:

- `--dry-run`: Show planned deletions without removing anything.
- `--all` or `-A`: Delete all workspaces regardless of state (still confirms
  remote branch deletion for unfinalized workspaces).
- `--yes` or `-y`: Delete without confirmation prompts (except remote branch
  deletion for unfinalized workspaces).
- `--no-branch`: Keep local/remote branches; delete only workspace folders.
- `--orphans`: Delete orphaned workspaces (missing config or repo directory).

Examples:

```sh
atelier clean --dry-run
atelier clean --all --yes
atelier clean --no-branch feat/old-branch
atelier clean --orphans
```

### `atelier remove` / `atelier rm`

Remove project data from the Atelier data directory without touching user repos.

Usage:

```sh
atelier remove
atelier remove <project-dir-name>
atelier remove --orphans
```

Options:

- `--all`: Remove all projects.
- `--installed`: Delete the entire Atelier data directory (projects +
  templates).
- `--orphans`: Remove orphaned projects (missing enlistment path).

### `atelier upgrade [workspace-branch ...]`

Upgrade project/workspace metadata and templates safely.

Usage:

```sh
atelier upgrade
atelier upgrade feat/old-branch
atelier upgrade --all-projects --dry-run
```

Options:

- `--installed`: Refresh the installed template cache.
- `--all-projects`: Upgrade all projects in the data directory.
- `--no-projects`: Skip project upgrades.
- `--no-workspaces`: Skip workspace upgrades.
- `--dry-run`: Show planned changes only.
- `--keep-modified`: Skip upgrading files modified since the last upgrade.
- `--yes`: Apply without confirmation.

## Development

Atelier is a Python 3.11+ CLI packaged with `uv`.

Global install (recommended for day-to-day use):

```sh
uv tool install --editable .
uv tool update-shell
```

Then open a new shell so the tool bin directory is on your PATH.

Common tasks (requires `just`):

```sh
just install
just install-dev
just test
just test-integration
just lint
just format
```

Install `just` with `brew install just` or `cargo install just`.

`just test-integration` runs publish-skill evals and requires the `codex` CLI to
be installed and authenticated.

```sh
uv venv
uv pip install -e .[dev]
```

Run the CLI locally:

```sh
uv run atelier --help
```

Run tests:

```sh
pytest
bash tests/shell/run.sh
```

## License

MIT. See LICENSE.
