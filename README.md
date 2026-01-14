# Atelier

Atelier is a local, filesystem-based workflow for agent-assisted software
development. It treats the filesystem as the primary unit of isolation so each
branch-worthy unit of work lives in its own workspace directory.

Atelier is:
- a basecamp, not an installer
- a protocol, not a framework
- a convention, not an enforcement mechanism

The repository provides conventions, templates, and small CLI scripts. It does
not manage your workspaces, run background services, or impose global setup.

## Why

Git branches are cheap, but a single working copy makes parallel work painful.
Atelier lets you run multiple agent or human sessions in parallel without
constantly switching branches or mixing intent.

## Core Ideas

- One workspace = one goal = one branch = one agent session
- Intent is written before code (in `AGENTS.md`)
- Workspaces are short-lived and disposable
- Text files are the source of truth

## Directory Layout

```
atelier/
├─ bin/                 # CLI helpers
├─ templates/           # Templates for projects and workspaces
├─ workspaces/          # User-owned, gitignored
│  └─ <project>/
│     ├─ project.yaml
│     ├─ AGENTS.md      # optional project-level instructions
│     └─ <workspace>/
│        ├─ AGENTS.md   # required workspace intent
│        └─ repo/       # git clone + branch
```

## Quick Start

1) Create a project container:

```
./bin/atelier-project <project>
```

2) Create a workspace:

```
./bin/atelier-workspace <project> <type> <slug>
```

Example:

```
./bin/atelier-project atelier
./bin/atelier-workspace atelier feat bootstrap-atelier
```

The workspace script will:
- read `project.yaml`
- clone the repo
- create a branch
- generate a workspace `AGENTS.md` with your intent

## Templates

Templates live in `templates/` and are rendered by the scripts. You can edit
these to match your preferences.

- `templates/project.yaml`
- `templates/project/AGENTS.md`
- `templates/workspace/AGENTS.md`

## Scripts

- `bin/atelier-project`: create a project container and `project.yaml`
- `bin/atelier-workspace`: create a workspace, clone repo, and branch

More scripts (`atelier-pr`, `atelier-clean`, `atelier-status`) can be added as
needed.

## Notes

- `workspaces/` is intentionally gitignored.
- No background processes, daemons, or global installers.
- Atelier assumes `git` (and optionally `gh`) are available.

## Design Constraints

- interactive prompts when info is missing
- clarity over cleverness
- bash-first, minimal dependencies
- safe, local, and disposable by default

## License

MIT. See LICENSE.
