# Atelier

Atelier is an installable CLI for workspace-based, agent-assisted development
inside local Git repos. It turns each unit of work into its own workspace with a
dedicated git checkout, explicit intent, and a predictable launch path for
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

## Why not `git worktree`?

Atelier does not use `git worktree` by default.

While `git worktree` is excellent for managing multiple checkouts of a
repository and optimizing storage, it operates at a lower abstraction level than
Atelier.

Atelier's primary abstraction is a *workspace*—a unit of intent, execution, and
lifecycle—not just another checkout.

Full, independent repositories provide clearer isolation, simpler cleanup, and
more predictable behavior than shared state for both humans and coding agents.

Disk is cheap. Cognitive overhead and invisible coupling are not.

Read more in [docs/why-not-git-worktree.md](docs/why-not-git-worktree.md).

## Core Ideas

- One workspace = one unit of work = one branch
- Intent is captured before code (in `SUCCESS.md`)
- Workspaces are isolated directories with their own `repo/`
- Projects are identified by their local enlistment path (each repo you
  initialize is a separate project), not Git origin
- The filesystem is the source of truth

## Behavior and Design Notes

See [docs/behavior.md](docs/behavior.md) for the compact behavioral overview.
Command-specific details live in module docstrings under `src/atelier/commands`.

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
- creates workspace folders keyed by branch name plus a stable hash
- maintains minimal `config.sys.json`/`config.user.json` state for projects and
  workspaces
- bootstraps policy/context files (`AGENTS.md`, `PROJECT.md`, `SUCCESS.md`,
  `PERSIST.md`, `BACKGROUND.md`)
- clones the repo and checks out workspace branches on demand
- launches your editor and configured agent in a predictable way

## Project Layout

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
         └─ <workspace-key>/
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

- `<project-key>` is the enlistment basename plus a short SHA-256 of the full
  enlistment path.
- `<workspace-key>` is the normalized branch name plus a short SHA-256 of the
  full workspace ID.

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

Open or create a workspace:

```sh
atelier open [workspace-branch]
```

If no branch is provided, Atelier will take over the current branch only when
the working tree is clean and the branch is fully pushed to its upstream.

Use `--raw` to treat the argument as the full branch name (no prefix lookup).

`atelier open` will:

- create the workspace if needed
- generate `AGENTS.md`, `SUCCESS.md`, `PERSIST.md`, and config files (plus
  `BACKGROUND.md` when the branch already exists)
- clone the repo into `repo/` and create the workspace branch
- prompt to remove the finalization tag `atelier/<branch-name>/finalized` if
  present (continuing either way)
- open `editor.edit` for new workspaces (`SUCCESS.md` by default), then launch
  the configured agent

Open a workspace repo in your work editor:

```sh
atelier work <workspace-branch>
atelier work <workspace-branch> --workspace
```

Open a shell in a workspace repo (or run a command there):

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
atelier clean --all --force
```

## Notes

- Template upgrades on `atelier open` are governed by `atelier.upgrade`
  (`always`, `ask`, `manual`).
- `SUCCESS.md` is the execution contract for each workspace.
- `AGENTS.md` is a managed, static prologue created in each workspace.
- `PERSIST.md` records integration guidance and the finalization tag
  (`atelier/<branch-name>/finalized`) used by `atelier clean`.
- `BACKGROUND.md` captures context when opening an existing branch.
- `PROJECT.md` is an optional policy overlay for agents and is linked/copied
  into each workspace.
- Configuration lives in `config.sys.json`/`config.user.json` under the Atelier
  data directory.
- Workspace directories are keyed by a stable hash of the branch name.

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

Examples:

```sh
atelier config --prompt
atelier config --reset
atelier config --installed --prompt
```

### `atelier template <project|workspace|success>`

Print or edit templates used to seed new documents.

Usage:

```sh
atelier template project
atelier template workspace
atelier template success
```

Options:

- `--installed`: Use the installed template cache.
- `--edit`: Open the resolved template in `editor.edit`.

Examples:

```sh
atelier template workspace --edit
atelier template workspace --installed
```

### `atelier edit [workspace-branch]`

Open editable docs in `editor.edit`.

Usage:

```sh
atelier edit --project
atelier edit scott/feat/new-search
```

### `atelier open [workspace-branch]`

Create or open a workspace, ensuring its `repo/` checkout exists, open
`editor.edit` for new workspaces (`SUCCESS.md` by default), then launch the
configured agent. New workspaces include managed `AGENTS.md`/`PERSIST.md`, and
`BACKGROUND.md` when the branch already exists. If the workspace repo has the
finalization tag `atelier/<branch-name>/finalized`, `atelier open` will prompt
to remove it but continues either way.

Usage:

```sh
atelier open feat/new-search
```

If no branch is provided, `atelier open` can take over the current branch only
when the working tree is clean and the branch is fully pushed to its upstream.
By default, `atelier open` rejects the default branch unless it was created via
`atelier new`.

Options:

- `--raw`: Treat the argument as the full branch name (no prefix lookup).
- `--branch-pr`: Override pull request expectation for this workspace.
- `--branch-history`: Override history policy for this workspace.

Examples:

```sh
atelier open scott/feat/new-search --raw
atelier open feat/new-search --branch-history squash
```

### `atelier work <workspace-branch>`

Open a workspace repo in `editor.work` without blocking the CLI. Use
`--workspace` to open the workspace root instead of `repo/`.

### `atelier shell <workspace-branch> [--] [command ...]`

Open a shell in the workspace repo, or run a command there. Use `--shell` to
override the interactive shell selection. Use `--workspace` to run in the
workspace root instead of `repo/`.

### `atelier exec <workspace-branch> [--] [command ...]`

Run a command in the workspace repo. This is an alias for `atelier shell` in
command-execution mode and requires a command. Use `--workspace` to run in the
workspace root instead of `repo/`.

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

- `--all` or `-A`: Delete all workspaces regardless of state (still confirms
  remote branch deletion for unfinalized workspaces).
- `--force` or `-F`: Delete without confirmation prompts (except remote branch
  deletion for unfinalized workspaces).
- `--no-branch`: Keep local/remote branches; delete only workspace folders.
- `--orphans`: Delete orphaned workspaces (missing config or repo directory).

Examples:

```sh
atelier clean --all --force
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
just lint
just format
```

Install `just` with `brew install just` or `cargo install just`.

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
```

## License

MIT. See LICENSE.
