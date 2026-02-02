# Northern Expedition — Atelier Toward Beads + Changesets

This document outlines the path to evolve Atelier into a beads-first system that
remains workspace-oriented, but moves intent, planning, and sequencing into
Beads. It reflects the planner/worker model and communication patterns from Gas
Town while keeping Atelier focused on accountability, reviewability, and
human-centric workflows.

It is a directional document, not a binding spec.

______________________________________________________________________

## Goals

- Make Beads the source of truth for intent, planning, and sequencing.
- Treat changesets as explicit, planned units of work before execution.
- Preserve deterministic, explicit behavior with no hidden automation.
- Keep Atelier lean by relying on Beads core capabilities.
- Maintain compatibility with repos that already use Beads.
- Enforce human-shaped changesets and reviewability.
- Run workers manually with no background agents.
- Backwards compatibility is not a goal.

______________________________________________________________________

## Current State

- Work is organized by epics, worktrees, and changeset branches.
- Intent lives in epic records with `workspace.root_branch` metadata.
- `atelier work` starts worker sessions.
- `publish` and finalization tags encode integration state.
- Changesets are planned, sequenced, and mapped to branches.

______________________________________________________________________

## Target State (Beads + Worktrees)

### Beads as Intent + Plan

- A workspace is associated with a top-level Beads issue (epic).
- Changesets are child Beads issues (tasks) under that epic.
- Dependencies inside Beads define the changeset sequence.
- Beads also carries coordination state: hooks, claims, and messaging.
- SUCCESS.md is not part of the workflow.

### Workspaces as Worktrees

- A workspace is a worktree tied to an epic bead.
- Worktrees are named after the epic bead id (optionally with a short slug).
- Changesets are branches, not separate worktrees, unless stronger isolation is
  required.

### Atelier as Execution Overlay

- Most state lives in Beads.
- Atelier stores execution-specific data in workspace config when needed:
  - branch mapping for changesets
  - PR metadata and review state
  - base/head commit SHAs
- Optional local SQLite locks can be used for claim atomicity.

______________________________________________________________________

## Concept Mapping

### Epic (Bead)

- Top-level bead representing a workspace intent.
- Hooks/claims determine ownership.
- The epic bead description may include structured key:value fields (e.g.,
  scope, acceptance, worktree path).

### Changeset (Bead)

- Child bead under the epic.
- Backed by its own branch.
- Dependency graph orders changesets.

### Agent (Bead)

- Each agent has a stable identity and bead record.
- Hooks are stored on the agent bead as the authoritative binding.

______________________________________________________________________

## Changeset Branch Naming

Default naming should be stable and derived from the root branch:

```
<root-branch>-<changeset-id>
```

Branch names are treated as immutable once created. If scope changes materially,
close the old changeset bead and create a new one with a new branch. Renames are
discouraged for auditability.

______________________________________________________________________

## Roles

### Planner (`atelier plan`)

- Creates epics, tasks, subtasks, and changesets.
- Encodes changeset guardrails in bead descriptions.
- Produces the dependency graph that governs sequencing.

### Worker (`atelier work`)

- Claims and hooks an epic.
- Executes tasks and changesets.
- Closes work and clears hooks.

### Worker Modes

- **prompt**: list available epics, ask user to choose.
- **auto**: claim the next eligible ready epic, or resume unfinished work.

______________________________________________________________________

## Command Evolution (Proposed)

### `atelier plan`

- Planner entrypoint.
- Creates epics and changeset graphs in Beads.
- Can be shallow (epic only) or deep (epic + changesets).

### `atelier work`

- Worker entrypoint.
- With an explicit epic id: claim and hook that epic.
- Without args: prompt (or auto mode) to claim the next eligible epic.
- Starts work on the next ready changeset for the chosen epic.
- `atelier open` is not part of the primary workflow.

### `atelier edit`

- Open the workspace repo in the configured work editor.

### `atelier status`

- Shows hooks, claims, queue state, and progress for epics/changesets.

### `atelier gc`

- Clears stale hooks, stale claims, and abandoned queues.

Agents should not call the `atelier` CLI directly. Agents use skills only.

______________________________________________________________________

## Beads Integration Contract

Atelier must rely on Beads core capabilities to stay compatible with existing
Beads repos.

### Required Beads Capabilities

- Create and update issues
- Parent/child relationships (epic -> tasks)
- Dependencies between tasks
- Status updates, including `hooked` / `pinned` when supported
- Labels and comments

### Messaging

- Message beads are first-class.
- For discussion, create a message bead with `thread: <bead-id>` in frontmatter.

### Compatibility Notes

- If Beads does not support custom statuses, represent `hooked` / `pinned` as
  labels and keep status at `open`.

### Avoid

- Custom schema changes inside Beads storage.
- Storing execution metadata directly in Beads beyond description fields,
  labels, and comments.

All Atelier-specific execution metadata should live in workspace config.

______________________________________________________________________

## Beads Location

- If a repo already uses Beads, Atelier integrates with that store.
- Otherwise, Atelier uses a project-level Beads store in its data directory.
- No prompting for creation; the location is a project config decision.

______________________________________________________________________

## Phased Roadmap

### Phase 0 — Beads Dogfooding

- Adopt Beads in this repo for Atelier planning.
- Create epics/tasks/changesets in Beads to validate workflows.
- Establish conventions for labels, types, and description fields.

### Phase 1 — Beads Foundation

- Detect Beads location (repo or project-level).
- Track epic bead id in workspace config.
- Add `atelier plan` and `atelier work` entrypoints.
- Add planner/worker AGENTS.md scaffolding.

### Phase 2 — Changesets + Sequencing

- Plan creates child beads (changesets) + dependency graph.
- Workspace stores changeset-branch mapping.
- `atelier work` starts on the next ready changeset for the chosen epic.

### Phase 3 — Review Lifecycle

- Encode PR/review state in workspace config.
- Skills update Beads comments/labels for review state.
- Re-evaluate finalization tags (optional deprecation).

### Phase 4 — Tightening

- Remove SUCCESS.md creation path for new workspaces.
- Formalize the Beads integration contract.

______________________________________________________________________

## Risks / Open Questions

- Beads status granularity is coarse; labels may be required for review phases.
- Custom bead types may not be supported; labels should be the fallback.
- Changeset branch naming must remain deterministic and reversible.

______________________________________________________________________

## Success Criteria

- Every workspace is backed by a Beads epic.
- Every changeset is a Beads task with dependencies.
- `atelier work` lands on the next ready changeset for the chosen epic.
- SUCCESS.md is not required for new workspaces.
- Integration state is explicit and reviewable without guesswork.
