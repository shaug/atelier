# Atelier

Atelier is an installable CLI for workspace-based, agent-assisted development
within a single project. It turns each unit of work into its own workspace with
a dedicated git checkout, explicit intent, and a predictable launch path for
agents and humans.

Atelier is:

- a project-scoped tool, not a global project manager
- a workspace-first workflow, not a branch-switching helper
- a convention with sharp edges, not a flexible framework

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
- Projects are identified by their local enlistment path, not Git origin
- The filesystem is the source of truth

## What the CLI Manages

Atelier is intentionally small. The CLI:

- registers a local enlistment as a project in the Atelier data directory
- creates workspace folders keyed by branch name plus a stable hash
- maintains minimal `config.json` state for projects and workspaces
- bootstraps policy/context files (`AGENTS.md`, `PROJECT.md`, `SUCCESS.md` (or
  legacy `WORKSPACE.md`), `PERSIST.md`, `BACKGROUND.md`)
- clones the repo and checks out workspace branches on demand
- launches your editor and Codex in a predictable way

## Project Layout

```
<atelier-data-dir>/
└─ projects/
   └─ <project-key>/
      ├─ config.json
      ├─ AGENTS.md
      ├─ PROJECT.md
      ├─ templates/
      │  ├─ AGENTS.md
      │  └─ SUCCESS.md
      └─ workspaces/
         └─ <workspace-key>/
            ├─ AGENTS.md
            ├─ PERSIST.md
            ├─ BACKGROUND.md (optional)
            ├─ SUCCESS.md
            ├─ config.json
            └─ repo/
```

Notes:

- `<project-key>` is the enlistment basename plus a short SHA-256 of the full
  enlistment path.
- `<workspace-key>` is the normalized branch name plus a short SHA-256 of the
  full workspace ID.
- Legacy projects/workspaces may still use `WORKSPACE.md` as the intent file.

## Quick Start

Initialize a project:

```sh
atelier init
```

Run this inside an existing Git repo; Atelier stores state in the data directory
and does not write files into the repo.

Open or create a workspace:

```sh
atelier open [workspace-branch]
```

If no branch is provided, Atelier will take over the current branch only when
the working tree is clean and the branch is fully pushed to its upstream.

Use `--raw` to treat the argument as the full branch name (no prefix lookup).

`atelier open` will:

- create the workspace if needed
- generate `AGENTS.md`, `SUCCESS.md` (or legacy `WORKSPACE.md`), `PERSIST.md`,
  and `config.json` (plus `BACKGROUND.md` when the branch already exists)
- clone the repo into `repo/` and create the workspace branch
- prompt to remove the finalization tag `atelier/<branch-name>/finalized` if
  present (continuing either way)
- open the configured editor for new workspaces (`SUCCESS.md` by default), then
  launch Codex

List workspaces:

```sh
atelier list
atelier list --status
```

Clean completed workspaces (finalization tag):

```sh
atelier clean
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

- Atelier never auto-updates existing workspaces or templates.
- `SUCCESS.md` is the execution contract for each workspace (legacy workspaces
  may still use `WORKSPACE.md`).
- `AGENTS.md` is a managed, static prologue shared across projects/workspaces.
- `PERSIST.md` records integration guidance and the finalization tag
  (`atelier/<branch-name>/finalized`) used by `atelier clean`.
- `BACKGROUND.md` captures context when opening an existing branch.
- `PROJECT.md` is an optional policy overlay for agents.
- Configuration lives in `config.json` under the Atelier data directory.
- Workspace directories are keyed by a stable hash of the branch name.

## CLI Reference

### `atelier --help` and `atelier --version`

Use `atelier --help` to view all commands and options. Use `atelier --version`
to print the installed version and exit.

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
- `--agent`: Agent name (currently only `codex`).
- `--editor`: Editor command (e.g., `cursor --reuse-window`).

Example:

```sh
atelier init --branch-prefix scott/ --branch-pr false --branch-history rebase
```

### `atelier open [workspace-branch]`

Create or open a workspace, ensuring its `repo/` checkout exists, open your
editor for new workspaces (`SUCCESS.md` by default), then launch Codex. New
workspaces include managed `AGENTS.md`/`PERSIST.md`, and `BACKGROUND.md` when
the branch already exists. If the workspace repo has the finalization tag
`atelier/<branch-name>/finalized`, `atelier open` will prompt to remove it but
continues either way.

Usage:

```sh
atelier open feat/new-search
```

If no branch is provided, `atelier open` can take over the current branch only
when the working tree is clean and the branch is fully pushed to its upstream.

Options:

- `--raw`: Treat the argument as the full branch name (no prefix lookup).
- `--branch-pr`: Override pull request expectation for this workspace.
- `--branch-history`: Override history policy for this workspace.

Examples:

```sh
atelier open scott/feat/new-search --raw
atelier open feat/new-search --branch-history squash
```

### `atelier list`

List workspaces for the current project.

Usage:

```sh
atelier list
atelier list --status
```

With `--status`, columns show whether each workspace repo is checked out, clean,
and pushed.

### `atelier clean`

Delete workspaces safely. By default, this removes only workspaces that have the
local finalization tag `atelier/<branch-name>/finalized`.

Usage:

```sh
atelier clean
atelier clean feat/old-branch refactor/api
```

Options:

- `--all` or `-A`: Delete all workspaces regardless of state.
- `--force` or `-F`: Delete without confirmation prompts.
- `--no-branch`: Keep local/remote branches; delete only workspace folders.

Examples:

```sh
atelier clean --all --force
atelier clean --no-branch feat/old-branch
```

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
python -m unittest discover -s tests
```

## License

MIT. See LICENSE.
