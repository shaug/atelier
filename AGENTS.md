# Atelier — Agent Instructions

This repository defines **Atelier**, an installable CLI tool for managing
workspace-based, agent-assisted development within a single project.

Agents working in this repository are expected to help **implement Atelier v2**
according to the specification in `docs/SPEC.md`.

______________________________________________________________________

## Core Philosophy

Atelier is:

- a **project-scoped tool**, not a global project manager
- a **workspace-first workflow**, not a branch-switching helper
- a **convention with sharp edges**, not a flexible framework

Atelier exists to make one thing easy:

> Treat every branch-worthy unit of work as its own isolated workspace, with
> explicit intent captured before code is written.

The filesystem is the source of truth. Configuration is explicit. Automation is
opt-in and conservative.

______________________________________________________________________

## What This Repository Is

This repository is:

- the **source code** for the Atelier CLI
- the **owner** of default templates (project and workspace `AGENTS.md`)
- the **authority** for how `atelier init` and `atelier open` behave

This repository is **not**:

- an Atelier-managed project
- a workspace container
- a place where user workspaces live

Atelier manages *other* projects — not itself.

______________________________________________________________________

## Scope of Work

When working in this repository, you may:

- implement or refine the Atelier CLI
- update templates shipped with the tool
- adjust schemas for `config.sys.json`/`config.user.json` files
- improve documentation and examples
- simplify behavior while preserving correctness

You should **not**:

- add global registries or background services
- auto-modify user files after creation
- invent migration or upgrade systems
- enforce coding conventions for managed projects
- add features not explicitly described in the spec

If a behavior is not in `docs/SPEC.md`, do not add it.

______________________________________________________________________

## Development Model (Dogfooding)

Atelier v2 should be developed **using Atelier itself**.

That means:

- Non-trivial changes should be worked on in real workspaces
- Each workspace should have a clear `AGENTS.md` describing intent
- Agents should follow the same “Read AGENTS.md and go” contract
- Humans should be able to interrupt, inspect, and continue work easily

However:

- This repository itself is **not** an Atelier project
- Do not assume `config.sys.json`/`config.user.json` exists here
- Do not manage this repo as a workspace

Dogfooding applies to *how* we work, not *where* state lives.

______________________________________________________________________

## Implementation Constraints

### Language & Tooling

- Implement Atelier in **Python 3.11+**
- Use **uv** for dependency and packaging management
- Produce an **installable CLI** (`atelier`)
- Prefer standard library functionality where possible

### CLI Behavior

- Commands must be deterministic and explicit
- Interactive prompting is preferred when information is missing
- Side effects must be obvious and scoped to the project directory
- Failure modes must be loud and safe

Do not add hidden behavior or implicit defaults.

______________________________________________________________________

## Templates

Templates shipped with Atelier are:

- copied at creation time
- never referenced live
- never auto-updated
- owned by the user after creation

The tool may ship updated templates in new versions, but existing files must
never be modified automatically.

______________________________________________________________________

## Authority Model

This `AGENTS.md` is authoritative for **work on the Atelier tool itself**.

When Atelier manages other projects:

- Project-level `AGENTS.md` defines the Atelier overlay
- Workspace-level `AGENTS.md` defines execution and intent
- Repository-level rules (if any) define coding conventions

Atelier must respect those boundaries strictly.

______________________________________________________________________

## Commit Messages

- Use Conventional Commits format: `<type>(<scope>): <subject>`
- Allowed types: feat, fix, docs, refactor, test, chore, build, ci, perf, style,
  revert
- Subject is imperative, present tense, no trailing period.
- Every commit must include a body that summarizes all changes since the
  previous commit. For the first commit, summarize the full change set.
- If squashing or rebasing, update the body to reflect the aggregated change.
- Use markdown in the body; prefer bullets for multiple changes.
- If a commit fixes an issue, add this as the final line of the commit body:
  `Fixes #<issue-number>`
- For multiple issues, add one `Fixes #...` line per issue.

______________________________________________________________________

## Verification

After the workspace goals are met, run:

- `just test`
- `just format`
- `just lint`

If any command is missing or fails due to missing tooling, do not substitute
alternatives; record the failure and reason.

______________________________________________________________________

## Workflow Requirements

- Run `just format` before making commits.
- Ensure `just lint` and `just test` pass before shipping changes.
- When merging PRs to `main`, keep merge commit messages non-Conventional (use
  the default “Merge pull request #...” message) so Release Please does not
  double-count changelog entries.
