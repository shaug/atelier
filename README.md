# Atelier

Atelier is an installable CLI for workspace-based, agent-assisted development
within a single project. It turns each unit of work into its own workspace
with a dedicated git checkout, explicit intent, and a predictable launch path
for agents and humans.

Atelier is:
- a project-scoped tool, not a global project manager
- a workspace-first workflow, not a branch-switching helper
- a convention with sharp edges, not a flexible framework

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
└─ workspaces/
   └─ <workspace-name>/
      ├─ AGENTS.md
      ├─ .atelier.workspace.json
      └─ repo/
```

## Quick Start

Initialize a project:

```
atelier init
```

Open or create a workspace:

```
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
- Configuration lives in `.atelier.json` and is owned by the tool.

## Development

Atelier is a Python 3.11+ CLI packaged with `uv`.

```
uv venv
uv pip install -e .
```

Run the CLI locally:

```
uv run atelier --help
```

Run tests:

```
python -m unittest discover -s tests
```

## License

MIT. See LICENSE.
