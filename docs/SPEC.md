# Atelier — Initial Project Specification

## 1. Purpose & Motivation

### Problem Statement

Git allows cheap branching, but local developer workflows often remain constrained by a **single working copy (“enlistment”) per project**. This creates artificial friction:

- Context switching via `git checkout` pollutes working state
- Parallel work is serialized by a single filesystem
- Agent-based tools (Codex, Claude Code, etc.) are forced to reason across unrelated changes
- Human intervention (debugging, refactoring, exploration) becomes costly mid-flow

Web-based agent tools solve this by creating **isolated environments per task**, but at the cost of:
- reduced local control
- poor integration with existing editors and tools
- friction when humans want to “take the reins”

### Core Insight

> **Every branch-worthy unit of work should be its own local workspace.**

A workspace is:
- isolated
- single-purpose
- short-lived
- equally operable by humans *and* agents

The filesystem—not Git branches—is the primary unit of isolation.

### Goal of Atelier

**Atelier is a local, filesystem-based workflow for agent-assisted software development**, enabling:

- parallel work across many features / experiments
- zero branch switching
- durable, explicit intent *before* an agent starts
- seamless handoff between agents and humans
- tool-agnostic operation (Codex, Claude Code, Cursor, VS Code, human-only)

Atelier is **not** an AI tool.
It is a **workspace protocol** that AI tools can operate within.

### Operational Model

Atelier is not installed or initialized via a script.

Instead, the Atelier repository itself is the long-lived **basecamp** for all work.
Users clone the Atelier repository once and periodically sync it to receive
updated scripts and templates.

All actual development work happens inside user-owned workspaces, which are
intentionally **gitignored** by the Atelier repository. Updating or syncing
Atelier must never modify, migrate, or invalidate existing workspaces.

Atelier provides:
- conventions
- templates
- helper scripts

It does **not** own or manage user work.

---

## 2. Conceptual Model

### Key Concepts

#### Project
A long-lived logical software project, usually (but not always) backed by a GitHub repository.

- Identified by name
- Has a canonical repo URL
- Defines defaults and invariants
- Contains many workspaces over time

#### Workspace
A short-lived, single-purpose working directory representing *one unit of work*.

- Maps 1:1 to a Git branch and PR
- Has an explicit goal and success criteria
- Is disposable after merge
- Is the **only scope visible to an agent session**

> One workspace = one goal = one branch = one agent session

#### Agent
Any coding agent (Codex, Claude Code, Gemini, Cursor, or human) operating within a workspace.

Agents are **clients** of Atelier, not first-class entities.

---

## 3. Directory Structure

Atelier manages a root directory (default `~/atelier`):

```
~/atelier/
├─ workspaces/              # user-owned, gitignored
│  ├─ <project>/
│  │  ├─ project.yaml
│  │  ├─ AGENTS.md          (optional, project-level)
│  │  ├─ <workspace>/
│  │  │  ├─ AGENTS.md       (workspace intent & contract)
│  │  │  ├─ repo/           (git clone + branch)
│  │  │  └─ codex/          (optional notes, summaries)
├─ bin/
│  ├─ atelier-project
│  ├─ atelier-workspace
│  ├─ atelier-pr
│  ├─ atelier-clean
│  └─ atelier-status
```

The `workspaces/` directory is intentionally excluded from version control.
Workspaces are disposable, user-owned, and must never be assumed to exist
or remain stable across Atelier updates.

### Design Principles

- **No repo pollution**: the actual project repo is untouched
- **Intent lives outside code**, but adjacent to it
- **Hierarchy defines authority** (via AGENTS.md)
- **Disk space is cheaper than cognitive load**

---

## 4. Authority & Configuration Model

### AGENTS.md Hierarchy (Most → Least Specific)

1. Workspace `AGENTS.md`
2. Project `AGENTS.md` (if present)
3. Repo `AGENTS.md` (canonical project rules)
4. Agent defaults

Rules:
- Higher levels may *constrain* behavior
- Lower levels may *not* override repo rules
- Agents must treat AGENTS.md as authoritative contracts

---

## 5. Configuration Files

### `project.yaml` (Required)

Machine-readable metadata for a project.

Example:

```yaml
project:
  name: gumshoe
  repo:
    url: git@github.com:org/gumshoe.git
    default_branch: main

workspace:
  branch_prefix: feat
  naming_pattern: "{type}-{slug}"

defaults:
  pr_base: main
  delete_branch_on_merge: true
  delete_workspace_on_merge: true
```

Used by:
- CLI tools
- workspace creation
- branch naming
- cleanup logic

The initial schema is intentionally minimal and may evolve over time.

---

## 6. Workspace AGENTS.md (Required)

This file must fully define the workspace *before* an agent starts.

### Required Sections

- Identity (project, workspace, branch)
- Goal
- Out of scope
- Success criteria
- Constraints / notes
- Workspace contract (lifecycle rules)
- Authority statement

The agent session should be able to start with:

> “Read AGENTS.md and proceed.”

No additional setup prompt should be required.

---

## 7. CLI Tools (Initial Scope)

Atelier does not provide an initialization or installation command.
Cloning the Atelier repository is sufficient to begin use.

### `atelier-project <name>`
Creates a new project container.

Responsibilities:
- Create `workspaces/<project>/`
- Prompt for repo URL (optional at first)
- Generate `project.yaml`
- Generate project-level `AGENTS.md` (optional)
- Optionally create GitHub repo via `gh`

No workspace is created yet.

`atelier-project` defines project-level metadata only.
It does not clone repositories or create branches.

All cloning and branch creation happens exclusively in `atelier-workspace`.

---

### `atelier-workspace <project> <type> <slug>`

Creates a new workspace.

Responsibilities:
1. Load `project.yaml`
2. Create workspace directory
3. Clone repo into `repo/`
4. Create new branch from default branch
5. Prompt for:
   - Goal
   - Out of scope
   - Success criteria
   - Optional ticket link
6. Generate workspace `AGENTS.md`
7. Open `AGENTS.md` in `$EDITOR`
8. Print next steps:

```text
cd ~/atelier/workspaces/<project>/<workspace>
<agent command>
```

This command is the only mechanism by which code is cloned and branches are created.

---

### `atelier-pr`

Run inside a workspace.

Responsibilities:
- Push branch
- Create PR via `gh`
- Record PR URL (optional)

---

### `atelier-clean`

Run after merge.

Responsibilities:
- Confirm PR merged
- Delete branch
- Delete workspace directory

---

### `atelier-status`

Shows active workspaces across projects.

---

### Script Design Philosophy

All Atelier scripts are designed to be:

- **Interactive-first**: if required arguments are missing, scripts must prompt
- **Prompt-driven**: flags are optional, not required
- **Bash-first**: implemented as portable shell scripts where practical
- **Minimal**: no background processes, daemons, or global state

Atelier scripts optimize for clarity, hackability, and personal productivity,
not broad distribution or strict portability guarantees.

---

## 8. Non-Goals (Explicit)

Atelier will **not**:

- manage tasks or tickets
- enforce workflow correctness
- integrate deeply with specific agents
- replace Git, PRs, or CI
- maintain long-lived state beyond the filesystem
- manage global configuration, installation, or environment setup

---

## 9. Key Design Constraints

- Tool-agnostic: must work with any agent or editor
- Text-first: Markdown and YAML only
- No background processes
- No server or daemon
- Safe by default
- Easy to abandon or fork

---

## 10. Success Criteria for Initial Version

The initial version of Atelier is successful if:

- A developer can run **multiple parallel agent sessions** on the same project locally without branch switching
- Each session has clear, durable intent defined *before* code generation
- Agents reliably operate only within their workspace
- A human can open any workspace in VS Code or Cursor and continue work
- Cleanup is trivial and leaves no residue

---

## 11. Development Approach (Meta)

This project **should be developed using Atelier itself**:

- Each feature/refactor of Atelier is its own workspace
- Codex (or other agents) are used as primary implementers
- Human acts as editor, reviewer, and architect

This dogfooding is intentional.

---

## Summary (For Codex)

> Atelier defines a local, workspace-oriented development protocol where each unit of work is isolated in its own directory, with explicit intent captured in AGENTS.md before any agent begins coding.
>
> Implement the initial CLI, templates, and documentation to support this workflow.
