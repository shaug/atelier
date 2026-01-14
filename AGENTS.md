# Atelier — Agent Instructions

This repository defines **Atelier**, a local, filesystem-based workflow for
agent-assisted software development.

Agents working in this repository are expected to help **implement Atelier
itself**, following the same principles Atelier promotes.

---

## Core Philosophy

Atelier is:

- a **basecamp**, not an installer
- a **protocol**, not a framework
- a **convention**, not an enforcement mechanism

The filesystem is the primary source of truth.
Text files (Markdown, YAML) are authoritative.
Scripts exist to reduce friction, not to encode intelligence.

---

## Scope of Work

When working in this repository, you may:

- implement or refine CLI scripts in `bin/`
- create or update templates for:
  - `project.yaml`
  - project-level `AGENTS.md`
  - workspace-level `AGENTS.md`
- improve documentation to clarify intent or usage
- simplify or remove unnecessary complexity

You should **not**:

- introduce global configuration or installation steps
- manage user workspaces directly
- assume ownership of files under `workspaces/`
- create background processes, daemons, or services
- over-engineer for portability or wide adoption

This tool is intentionally personal-first.

---

## Development Model (Dogfooding)

Atelier should be developed **using Atelier itself**.

That means:

- Each non-trivial change should conceptually correspond to a workspace
- Intent should be clear before implementation
- Changes should be reviewable and incremental
- The design should remain coherent when used by:
  - Codex
  - Claude Code
  - Cursor
  - humans editing files directly

---

## Script Design Constraints

When implementing or modifying scripts:

- Prefer **interactive prompts** when information is missing
- Prefer **clarity over cleverness**
- Use Bash where practical
- Avoid unnecessary dependencies
- Assume `git` and `gh` are available
- Fail safely and loudly when assumptions are violated

Do not invent complex flag systems unless clearly justified.

---

## Authority Model

This `AGENTS.md` is authoritative for work on the Atelier repository itself.

When Atelier is used to manage other projects:

- Project-level and workspace-level `AGENTS.md` files define behavior
- Atelier does not override those instructions
- Atelier only provides structure and tooling

---

## How to Begin

To start work:

1. Read `docs/SPEC.md`
2. Identify the smallest useful next change
3. Implement it cleanly
4. Stop when the change is complete

If unsure what to do next, ask for clarification rather than guessing.
