# Ticketing Proposal (Skill-First)

This proposal defines how Atelier should support third-party ticketing systems
with minimal core coupling.

## Goals

- Keep Beads as Atelier's source of truth for planning/execution state.
- Let external ticket systems be optional, pluggable adapters.
- Prefer skill-driven integration over built-in provider logic.
- Keep onboarding simple: detect what is available, then ask once.

## Non-goals

- Full bidirectional sync by default.
- Mandatory provider setup during `atelier init`.
- Embedding provider-specific API complexity in core commands.

## Core model

- **Atelier Bead**: canonical local work record.
- **External Ticket Link**: normalized metadata in `external_tickets`.
- **Provider Adapter**: capability layer used by planner skills.
- **Ticket Orchestrator Skill** (`tickets`): single entrypoint planner uses.

Core CLI remains responsible for schema, validation, and readiness checks.
Provider API behavior belongs in skills.

## Detection and selection

Detection runs at planner startup (and on explicit request).

Inputs:

- `config.user.json` provider hint (if set).
- repo signals (`origin` slug, repo-local `.beads`).
- skill availability in known skill lookup locations.

### Skill lookup locations

Atelier should discover ticketing skills from:

1. `project_data/skills` (installed packaged/project-local skills).
1. Agent-specific project/global skill lookup paths from `agents.AgentSpec`:
   - `project_skill_lookup_paths`
   - `global_skill_lookup_paths`

The new agent lookup abstraction is the canonical source for agent-specific
paths.

### Capability manifest

Each provider skill should include a machine-readable manifest, for example:

`skill.json` (or front matter in `SKILL.md`) with:

- `kind: "ticket-provider"`
- `provider: "github" | "linear" | "jira" | ...`
- `operations: ["import", "create", "link", "set_in_progress", ...]`
- `priority: <int>` (optional, for tie-breaks)

### Selection algorithm

1. Build candidate providers from config + repo signals + manifests.
1. Filter to providers with required minimum operations:
   - `import`
   - `create` OR `link`
   - `set_in_progress` (or explicit `unsupported`)
1. Rank candidates:
   - explicit config provider first
   - repo-native providers next (`github` for GitHub remotes, `beads` for repo
     `.beads`)
   - remaining by manifest priority/name
1. Prompt user when multiple viable providers exist.
1. Persist choice in config for future sessions.

If no provider is selected, planner runs Beads-only mode.

## Runtime contract

Planner talks only to the `tickets` orchestrator skill with normalized payloads.

The `tickets` skill delegates to provider skills (`github-issues`, `linear`,
etc.) and returns normalized records for core merge/validation.

Core command behavior:

- never trusts provider payloads without schema validation.
- never blocks worker readiness on remote state.
- logs provider actions and failures explicitly.

## Lifecycle policy

- Local bead state remains authoritative.
- External updates are explicit planner actions (import/sync/export), not hidden
  side effects.
- Worker sessions may call `set_in_progress` when supported, but local progress
  continues even if remote update fails.

## UX flow

At `atelier init`:

- ask whether to enable external ticket integration now.
- if yes, run detection and save selected provider.
- if no, keep project in Beads-only mode.

At `atelier plan` startup:

- show detected provider + capability summary.
- optionally prompt to import/sync external tickets for planning context.

## Rollout phases

1. **Phase 1: Detection**
   - provider manifest format
   - path-based skill discovery using agent lookup abstraction
   - startup provider selection + persistence
1. **Phase 2: Orchestrator hardening**
   - strict `tickets` skill request/response contract
   - consistent error surfaces and logging
1. **Phase 3: Provider packs**
   - first-party skill packs for GitHub/Linear/Jira
   - import/export/sync behavior tests
1. **Phase 4: Policy controls**
   - per-provider sync policies
   - optional conflict resolution helpers

## Open decisions

- Manifest location: dedicated `skill.json` vs `SKILL.md` front matter.
- Whether `set_in_progress` should be best-effort or optional-by-default.
- How aggressively planner should auto-suggest provider switches when repo
  signals change.
