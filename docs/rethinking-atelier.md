# Atelier Design Draft

This document describes Atelier: a tool for agent-assisted development and
automation focused on human-centric workflows that respect human cognitive
capacity and oversight. Atelier supports both PR/approval-heavy workflows and
lighter modes without explicit PRs, while still enforcing human-shaped
changesets. It is inspired by [Gas Town](https://github.com/steveyegge/gastown)
and its [Beads](https://github.com/steveyegge/beads) mechanics, but its
sensibility prioritizes accountability and reviewability over maximizing
throughput.

It focuses on planner vs worker roles, bd (Beads) formats and usage, Atelier
commands (overseer-only), and the skill set agents use to operate inside the
system.

## Goals

- Human-centric automation with optional explicit review/approval checkpoints.
- Workspace-oriented flow: work is scoped to a purpose via epic-linked worktrees
  and changeset stacks.
- Workers are started manually in separate terminals.
- No background agents. All automation happens via skills once a session starts.
- Most state lives in bd; optional local SQLite only for stronger claim
  atomicity.
- Planner creates epics + tasks + subtasks with changeset guardrails.
- Workers claim and own epics until completion or session end, and can move
  between epics over time.

## Roles

### Planner (Atelier Plan)

Purpose: create epics, tasks, and subtasks from a user goal. Enforce changeset
sizing and decomposition rules.

Responsibilities:

- Create epic beads.
- Create task + subtask beads under epics.
- Create required changeset beads (PR-sized units).
- Encode changeset guardrails in bead descriptions.

Planner worktree:

- Planner sessions run in a dedicated worktree per planner identity.
- Treat the worktree as read-only for code changes (no commits beyond beads).
- Use it as a reference canvas for planning and decomposition only.

### Worker (Atelier Work)

Purpose: claim an epic, execute its tasks and subtasks, and close the epic.

Responsibilities:

- Claim an available epic.
- Hook the epic to itself.
- Work through tasks/subtasks.
- Close completed tasks and the epic.
- Clear hook on completion.

Epic completion rule:

- When all changesets under an epic are either `cs:merged` or `cs:abandoned`,
  evaluate whether any additional work needs to be defined. If not, close the
  epic. If more work is required, create new changesets before closing. Status
  output reports `ready_to_close` when no remaining changesets exist; use
  `work_done` to close the epic and clear the hook.

### Worker Modes

Workers can run in one of two modes:

- **prompt**: list available epics and ask the user which epic to claim next.
- **auto**: claim the next eligible epic automatically when idle.

Mode should be set via environment variable or runtime config:

- `ATELIER_MODE=prompt|auto`

Prompt mode flow:

1. List available epics.
1. Ask the user to select an epic ID.
1. Claim the selected epic.

If the agent already has assigned epics, prompt mode lists them under “Resume
epics” (most recent first) and allows selecting one to reattach.

Auto mode flow:

1. Claim the next eligible *ready* epic.
1. If none are ready, pick up an unfinished epic.
1. On completion, repeat.

Auto mode default should prefer new ready epics over unfinished work. Users can
explicitly target unfinished epics via command-line or by reusing an existing
session. Auto mode selects the oldest ready epic first (by created time), then
falls back to the oldest unfinished epic already assigned to the agent.

## Atelier Data Directory

Atelier stores its data in a dedicated, platform-dependent data directory (e.g.,
XDG on Linux, `~/Library/Application Support` on macOS). Agent directories can
use symlinks so each agent stays self-contained and does not need to look
outside its own directory.

## Layout

```
<atelier-data>/
  beads/              # Atelier bd database (BEADS_DIR)
  config.json         # Project config (roles, defaults)
  skills/             # Linked Agent Skills (worker API)
  agents/             # Per-agent home dirs with role-specific AGENTS.md
  worktrees/          # Per-epic worktrees of the source project
```

### Per-Agent Home Directories (Recommended)

Each agent has a stable home directory for identity and instructions:

```
.atelier/agents/alice/AGENTS.md
.atelier/agents/plan-1/AGENTS.md
```

This keeps identity out of repo worktrees and avoids polluting the project
checkout. Do not add or modify AGENTS.md inside the repo worktrees for Atelier
purposes.

## Worktrees

Worktrees are the concrete realization of the “workspace” concept. Epics are
associated with specific worktrees, and workers can move between epics (and
their worktrees) over time while the system preserves state in beads.

Worktrees should be named after the epic bead ID they implement. This is
deterministic and makes GC, status, and audit trails reliable.

Recommended layout:

```
worktrees/<epic-id>/
```

Optional: include a short slug if you need readability:

```
worktrees/<epic-id>-<short-slug>/
```

Store the worktree path in the epic bead description:

```
worktree_path: worktrees/at-abc12
```

Changesets should always have a corresponding bead that is a child of the epic.
In PR-based workflows, each changeset bead maps to its own branch and PR.
Changesets should be branches, not separate worktrees, unless you need stronger
isolation.

## Changeset Branch Naming

Default naming should be stable and derived from the workspace root branch and
changeset bead ID:

```
<root-branch>-<changeset-id>
```

Branch names should be treated as immutable once created. If scope changes
materially, close the old changeset bead and create a new one with a new branch.
If no PR exists yet, renaming is possible but discouraged for auditability.

## Identity (Agent IDs)

Agents must use stable, human-meaningful identities, not process IDs. Use a
predictable format such as:

```
atelier/<role>/<name>
```

Examples:

- `atelier/planner/plan-1`
- `atelier/worker/alice`

Why stable IDs:

- Claims and hooks must survive restarts.
- Mail threading and audit trails need consistent attribution.
- GC/prune can reconcile stale claims without ambiguity.

### Identity Injection

Identity should be injected in the agent’s environment (source of truth), and
mirrored in AGENTS.md for transparency.

Recommended env vars:

- `ATELIER_AGENT_ID=atelier/worker/alice`
- `BD_ACTOR=atelier/worker/alice` (for bead attribution)
- `BEADS_AGENT_NAME=atelier/worker/alice` (for bead routing/slots)

Agent bead IDs should be derived from the stable identity, e.g.:

- `at-worker-alice`
- `at-planner-plan-1`

## Beads (bd) Format and Usage

### Core Bead Fields

Beads are records with at least:

- id, title, description, status, priority, issue_type
- assignee, labels, created_by, updated_by

### Description as Structured Fields

Atelier uses key: value lines in description (human readable + machine
parsable). Empty fields should be written as `null`.

### Labels for Message Metadata

Messages store metadata in YAML frontmatter at the top of the message body so
the message content can remain Markdown. Labels can mirror key fields for
indexing and query performance.

Frontmatter fields (recommended):

- from: <identity>
- thread: <thread-id>
- reply_to: <msg-id>
- msg_type: task|scavenge|notification|reply
- cc: \[<identity>, ...\]
- queue: <name>
- channel: <name>
- claimed_by: <identity>
- claimed_at: <rfc3339>
- retention_days: <int>
- expires_at: <rfc3339>

### Message Bead Shape

Message beads should be shaped as:

- type: message
- title: subject line
- description: YAML frontmatter + Markdown body
- assignee: recipient identity (direct messages)

Message beads are first-class; do not rely on generic comments plus inbox
queries as a substitute. For bead-specific discussion, use a message bead with
`thread: <bead-id>` in frontmatter.

### Recommended Bead Types and Labels

Agent beads:

- type: agent (custom type)
- label: at:agent

Epic beads (choose one):

- type: epic (custom type) OR
- type: task + label at:epic

Draft epic state:

- label: at:draft
- status: open (not hooked)
- workers must ignore epics with at:draft

Task beads:

- type: task + label at:task

Subtask beads:

- type: task + label at:subtask

Changeset beads (required):

- type: task + label at:changeset

Message beads:

- type: message (custom type)
- label: at:message

Queue/channel/group control beads (optional):

- labels: at:queue, at:channel, at:group

### Agent Bead Description Fields

```
role_type: worker|planner
agent_state: spawning|working|idle|done
hook_bead: <bead-id> | null
notification_level: verbose|normal|muted
heartbeat_at: <rfc3339> | null
```

### Epic Bead Description Fields

```
scope: <short scope>
acceptance: <exit criteria>
changeset_strategy: <rules or link to rules>
claim_expires_at: <rfc3339> | null
drafted_by: <agent-id> | null
```

### Hooking and Ownership

Claiming an epic means:

- epic.status = hooked
- epic.assignee = <agent-identity>
- agent.hook_bead = <epic-id>

The hook should be stored in the agent bead’s hook slot (bd slot set/clear) as
the authoritative source of truth. `hook_bead` in the description is a legacy
fallback and may be backfilled into the slot during reads. Only one hook per
agent.

### Pinned vs Hooked

Use these statuses consistently:

- **hooked**: active, assigned work on an agent’s hook.
- **pinned**: long-lived reference beads that should never be closed (e.g.,
  handoff notes, evergreen instructions).

### Draft Epics (Planner Iteration)

Planners may create epics ahead of time and iterate on breakdown without workers
claiming them. Use the `at:draft` label to mark an epic as not ready for
claiming. When ready, remove `at:draft` (optionally add `at:ready`).

Worker claim filters should require:

- label `at:epic`
- NOT label `at:draft`
- `assignee` empty
- `status=open`

## Molecules (Optional Workflow Layer)

Molecules are multi-step workflow instances built from formulas. Atelier can use
molecules to enforce structured lifecycles beyond the initial epic/task
breakdown (e.g., review cycles, QA gates, or PR feedback loops).

Recommended usage:

- **Epic planning**: still use epics/tasks/subtasks for the initial breakdown.
- **Changeset lifecycle**: attach a molecule to each changeset when it enters
  review (e.g., “address feedback → update tests → rebase → resubmit”).
- **Project defaults**: allow projects to define a default molecule for
  changeset workflows in `config.json`.

Molecules are not required in v1, but the system should reserve space for them
and keep the data model compatible (e.g., attachment fields or molecule IDs).

## PR/MR Workflows (Future)

Atelier should support explicit PR/MR workflows without requiring a dedicated
agent role. The workflow can be implemented via skills and/or molecules.

### Changeset Lifecycle (Review Projects)

Changesets move through a deterministic lifecycle, but PR states are computed
from Git/PR data rather than stored as bead labels or description fields.

Use `cs:` labels only for intent and non-derivable state:

- **cs:planned**: changeset bead exists but no branch/PR yet.
- **cs:ready**: ready to be claimed by a worker.
- **cs:in_progress**: work underway (local commits allowed).
- **cs:merged**: integrated/merged.
- **cs:abandoned**: closed without integration.

When a PR is merged or closed without merge, update labels to add
`cs:merged`/`cs:abandoned` and clear active labels (`cs:ready`, `cs:planned`,
`cs:in_progress`).

PR-derived (computed) states:

- **pushed**: remote branch exists, no PR yet.
- **draft-pr**: PR exists and is draft.
- **in-review**: PR ready *and* a non-bot reviewer assigned.
- **approved**: PR has approvals (even if unresolved threads remain).
- **merged**: PR merged.

Rules:

- No separate “changes requested” state.
- For non-review projects, use `cs:merged` when integrated and `cs:abandoned`
  when closed without integration.

In PR-based workflows, each changeset bead maps to:

- a branch
- a PR/MR
- a review lifecycle (which can be modeled as a molecule)

## External Ticket Integration (Future)

Atelier should support linking beads to external tickets without importing the
entire external system into beads. Use explicit fields and labels to preserve
traceability and define close/sync behavior. A bead may be associated with
multiple external tickets, which may represent different facets of the same
solution.

Recommended epic/task fields (YAML frontmatter, nested schema):

- external_tickets:
  - provider: github|linear|jira|<custom> id: <id or key> url: <url> state:
    <state> on_close: comment|close|sync|none
  - provider: ...

Recommended labels:

- ext:github / ext:linear / ext:jira

Integration should be handled by skills (e.g., `external_import`,
`external_sync`, `external_close`), with optional molecules for multi-step
sync/approval workflows.

## Startup Contract (Enforcement)

The startup contract (“check hook → if hooked, run it → if empty, check
inbox/queue”) should be enforced via:

- Per-agent `AGENTS.md` in `<atelier-data>/agents/<name>/`.
- A session-start skill that runs immediately on agent boot.
- An initial bootstrap message only if the runtime requires it.

AGENTS.md is the primary source of behavior; skills are the execution mechanism.
Use the `startup_contract` skill to sequence hook checks, inbox/queue handling,
and claiming new epics. The fallback ordering is: resume hooked epic, then stop
if there are unread message beads or unclaimed queue items, then choose a new
epic (auto = oldest ready, else oldest assigned; prompt = user selection). If no
eligible epics exist, emit a `NEEDS-DECISION` message to the overseer.

## Claiming Strategy (Atomicity)

### Option A: bd-only (simpler)

Attempt to claim with:

```
bd update <epic-id> --assignee=<agent> --status=hooked
```

Re-read and verify assignee. If mismatched, release and retry.

### Option B: SQLite lock (stronger)

Use a local SQLite table:

```
claims(bead_id PRIMARY KEY, agent_id, claimed_at)
```

Insert claim first; if success, update the bead. `atelier gc` cleans stale
locks.

## Changeset Guardrails (Planner)

Embed these in planning skills:

- Separate renames from behavioral changes.
- Prefer additive-first changesets.
- Defer user-visible or API-exposed changes.
- Target ~200 to 400 lines of code per changeset.
- Split if a changeset exceeds ~800 lines unless purely mechanical.
- Keep tests with their closest production change.
- Require explicit approval for >800 LOC changesets and record the approval in
  notes.

## Atelier CLI (Overseer Only)

User-facing commands should be minimal:

- `atelier plan` -> start planner session
- `atelier work` -> start worker session
- `atelier edit` -> open a workspace repo in the work editor
- `atelier status` -> show hooks, claims, queue state
- `atelier gc` -> cleanup stale hooks, claims, channels, queues

Agents should not call `atelier` directly. Agents use skills only.

## Agent Skills (Agent-Only API)

Skills live in `skills/` and wrap all interactions with bd.

Core skills:

- `claim_epic` -> atomically claim the next epic, update hook
- `release_epic` -> clear claim + hook
- `hook_status` -> show current hook + epic status
- `work_done` -> close epic and clear hook
- `heartbeat` -> update agent heartbeat (for gc)

Selection skills (prompt mode):

- `epic_list` -> list available epics with summary fields
- `epic_claim` -> claim a specified epic ID

Planner extension:

- `epic_list --show-drafts` -> include draft epics for review/iteration

Planner skills:

- `plan_create_epic`
- `plan_split_tasks`
- `plan_changesets` (enforce guardrails)

Messaging skills:

- `mail_send`
- `mail_inbox`
- `mail_mark_read`
- `mail_queue_claim` (if queues are enabled)
- `mail_channel_post` (if channels are enabled)

## Messaging Policy (When to Send Mail)

Messages are for coordination and exceptions. The hook is the assignment
channel.

### Send a message when:

- **Clarification is needed**: requirements or acceptance criteria are unclear.
- **Blocked**: missing access, failing tests with unknown cause, external
  dependency.
- **Approval is required**: changeset guardrails would be exceeded.
- **Scope changes**: epic needs splitting/merging, or new epics are required.
- **Handoff**: a session is ending mid-work; summarize state and next steps.
- **Status exceptions**: repeated failures or no eligible epics available.

### Do NOT message when:

- Assigning work (use claim + hook).
- Sending routine progress updates (unless explicitly requested).

### Overseer/Planner Messaging

Overseer and planner may message workers for meta-coordination:

- Acceptance criteria changed
- Size guardrails tightened
- Work paused or resumed
- Epic split/merge instructions

### Subject Conventions (Optional)

- `BLOCKED: <reason>`
- `NEEDS-DECISION: <question>`
- `SCOPE-CHANGE: <summary>`
- `PAUSE: <reason>`
- `RESUME: <condition met>`

### Skill Trigger Rules (Recommended Defaults)

- **Blocked > 15 minutes** -> `mail_send` to overseer with `BLOCKED:` subject.
- **Changeset guardrail violation** -> `mail_send` to overseer with
  `NEEDS-DECISION:`.
- **No eligible epics** -> `mail_send` to overseer with
  `NEEDS-DECISION: No eligible epics`.
- **Scope split required** -> `mail_send` to planner with `SCOPE-CHANGE:`.
- **Session ending mid-work** -> `mail_send` with `HANDOFF:` summary.

## AGENTS.md (Worker Instructions)

Must instruct:

- You are a worker inside Atelier.
- Do not call `atelier` CLI directly.
- Use skills for claim, hook, mail, close.
- On startup: claim epic, hook it, and begin work immediately.
- If no epic is available: check mail, then idle.

## Cleanup (atelier gc)

Should handle:

- Release epics with missing session or stale heartbeat.
- Clear agent hooks pointing to closed or unassigned epics.
- Prune message channels by retention policy.
- Release queue claims that are stale.

## Reliability Notes

Use bd as source of truth for work state. If SQLite claims are used, treat them
as a guardrail only; reconcile with bd during gc.

All skill commands should be idempotent and return structured output for the
agent to reason about retries.
