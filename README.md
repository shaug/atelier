# Atelier

Atelier is an installable CLI for workspace-based, agent-assisted development
within a single project. It turns each unit of work into its own workspace
with a dedicated git checkout, explicit intent, and a predictable launch path
for agents and humans.

Atelier is:

- a project-scoped tool, not a global project manager
- a workspace-first workflow, not a branch-switching helper
- a convention with sharp edges, not a flexible framework

## Inspiration

Atelier is inspired by the ideas explored in
[*Shipping at Inference Speed*](https://steipete.me/posts/2025/shipping-at-inference-speed),
which argues that many traditional Git workflows introduce unnecessary
cognitive overhead when working with fast, capable coding agents.

In particular, the essay highlights the value of:
- minimizing mental context switches
- evolving codebases linearly when coordination cost is low
- treating LLMs as collaborators, not batch tools

Atelier adopts these ideas where they help, while still supporting
branch- and review-based workflows when coordination and safety matter.
It's an adaptation of the essay's philosophy, not a clone.

Read more in [docs/inspiration.md](docs/inspiration.md).

## Why “atelier”?

*Atelier* (pronounced **ah-tuh-lee-AY**) is the French word for a workshop.

The name reflects how this tool is intended to be used: as a place where
work is shaped iteratively, with humans and tools collaborating closely.

Atelier is not a factory pipeline or a fully automated system. It favors
explicit intent, interruption, and hands-on control over invisible
automation.

Agents are collaborators, not background jobs—and the human is always
allowed to step back in and take the reins.

The name is meant to signal craft and collaboration, not art, magic, or
opacity.

Read more in [docs/atelier-name.md](docs/atelier-name.md).

## Why not `git worktree`?

Atelier does not use `git worktree` by default.

While `git worktree` is excellent for managing multiple checkouts of a
repository and optimizing storage, it operates at a lower abstraction level
than Atelier.

Atelier's primary abstraction is a *workspace*—a unit of intent,
execution, and lifecycle—not just another checkout.

Full, independent repositories provide clearer isolation, simpler cleanup,
and more predictable behavior than shared state for both humans and coding
agents.

Disk is cheap. Cognitive overhead and invisible coupling are not.

Read more in [docs/why-not-git-worktree.md](docs/why-not-git-worktree.md).

## Core Ideas

- One workspace = one unit of work = one branch
- Intent is captured before code (in `AGENTS.md`)
- Workspaces are isolated directories with their own `repo/`
- The filesystem is the source of truth

## Project Layout

```
project-dir/
├─ .atelier.json
├─ AGENTS.md
├─ PROJECT.md
├─ templates/
│  └─ WORKSPACE.md
└─ workspaces/
   └─ <workspace-name>/
      ├─ AGENTS.md
      ├─ WORKSPACE.md
      ├─ .atelier.workspace.json
      └─ repo/
```

## Quick Start

Initialize a project:

```sh
atelier init
```

Optionally create a workspace policy template:

```sh
atelier init --workspace-template
```

Open or create a workspace:

```sh
atelier open <workspace-name>
```

`atelier open` will:

- create the workspace if needed
- generate `AGENTS.md` and `.atelier.workspace.json`
- clone the repo into `repo/` and create the workspace branch
- launch the configured editor and Codex

## Notes

- Atelier never auto-updates existing workspaces or templates.
- `AGENTS.md` is the execution contract for each workspace.
- `PROJECT.md` and `WORKSPACE.md` are optional policy overlays for agents.
- Configuration lives in `.atelier.json` and is owned by the tool.

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
