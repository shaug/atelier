# External Ticket Integration Addendum

This addendum defines how Atelier models external tickets and how integration
should work with the planning agent.

It extends `/Users/scott/code/atelier/docs/SPEC.md` and is authoritative for
external ticket linkage, synchronization semantics, and provider integration
contracts.

## Goals

- Keep local Atelier beads as the source of truth for planning and execution.
- Allow explicit import/export links to external systems (GitHub, Linear, Jira,
  repo-local Beads, custom).
- Ensure worker-ready beads are fully actionable without external lookups.

## Core principles

- Local-first: local bead content is authoritative and may be a superset of
  remote tickets.
- Explicit sync: synchronization is user- or planner-requested, not implicit.
- Many-to-many mapping: one bead can map to many external tickets, and many
  beads can map to one external ticket.
- Context imports: some imported tickets may be reference-only context and not
  intended for local execution.

## Canonical linkage model

`external_tickets` remains a JSON list stored in bead description fields.

Recommended per-entry fields:

- `provider`: provider slug (`github`, `linear`, `jira`, `beads`, `custom`).
- `id`: provider ticket id/key.
- `url`: canonical remote URL when available.
- `relation`: role of this ticket relative to the bead.
- `direction`: provenance of association.
- `sync_mode`: sync policy for this link.
- `state`: normalized cached remote state.
- `raw_state`: optional provider-native state string.
- `state_updated_at`: optional timestamp for cached state.
- `parent_id`: optional provider parent ticket id (for hierarchical systems).
- `on_close`: optional close behavior (`none`, `comment`, `close`, `sync`).
- `last_synced_at`: optional last successful sync timestamp.

### `relation`

Defines why a ticket is linked.

- `primary`: main outward-facing ticket for this bead.
- `secondary`: additional ticket tracking the same local work.
- `context`: reference-only ticket imported to enrich local context graph.
- `derived`: child/split ticket created from another linked ticket.

Usage:

- Select default push target (`primary` first).
- Distinguish execution targets from context-only references.
- Preserve lineage when one remote ticket is split across multiple local beads.

### `direction`

Defines how the association was established.

- `imported`: remote ticket existed first and was imported.
- `exported`: local bead existed first and was exported.
- `linked`: local and remote records were manually associated.

Usage:

- Explain provenance in planner summaries and audits.
- Drive safer default sync behavior and conflict prompts.

### `state`

Represents a normalized cached snapshot of remote status. It is not the local
source of truth.

Suggested values:

- `open`
- `in_progress`
- `blocked`
- `in_review`
- `closed`
- `unknown`

Usage:

- Planner visibility and filtering.
- Optional sync/reporting.
- Never required for worker readiness.

## Planner contract (`atelier plan`)

Planner is the orchestrator for external ticket synchronization.

- On session start, planner may offer optional import/sync for configured
  providers.
- On explicit request, planner can import external tickets as:
  - actionable work seeds (`relation=primary|secondary`)
  - context graph nodes (`relation=context`)
- During planning, planner can export selected local beads to remote providers.
- Before a bead is marked ready for worker execution, planner must ensure local
  bead content is complete and actionable without external provider calls.

### Planner sync flow

- Startup prompt: ask whether to import or sync external tickets for configured
  providers, with a default of no action unless the user opts in.
- Import flow:
  - pick provider, optional query/filter, and target purpose (actionable vs
    context).
  - create new beads or link existing ones; default `direction=imported` with
    `relation` based on the chosen purpose.
- Export flow:
  - after planning, offer to export selected beads; default `relation=primary`,
    `direction=exported`, and `sync_mode=export`.
  - allow mapping multiple beads to a single external ticket when needed, while
    preserving `relation` and `parent_id` metadata when provided by the
    provider.
- On-demand sync: planner exposes explicit actions to refresh cached state or
  push local updates when a provider declares capability support.

### Planner environment

Planner sessions expose provider context to the agent via environment variables.
These are optional hints and should not be treated as authoritative.

- `ATELIER_EXTERNAL_PROVIDERS`: comma-separated provider slugs.
- `ATELIER_GITHUB_REPO`: GitHub repo slug (`owner/name`) when available.

## Readiness and completeness

Beads linked to external tickets are only worker-ready when local content is
complete and self-contained.

Required for worker readiness:

- Title and description capture the full intent, constraints, and acceptance
  criteria needed to execute without external lookups.
- `external_tickets` entries include `relation` and `direction` when known, so
  planner can distinguish actionable work from context references.
- Any required context from external systems is copied into the bead body or
  linked local notes before the bead is marked ready.

Optional behaviors:

- When local content meaningfully exceeds the external ticket, planner may offer
  a push-back option to update the external ticket body or notes.
- External state sync is never required for readiness; it is strictly optional.

## Examples

Example `external_tickets` entry for a primary GitHub issue:

```json
[
  {
    "provider": "github",
    "id": "1234",
    "url": "https://github.com/org/repo/issues/1234",
    "relation": "primary",
    "direction": "imported",
    "sync_mode": "import",
    "state": "open",
    "on_close": "comment"
  }
]
```

Example with a context-only ticket and a derived child ticket:

```json
[
  {
    "provider": "linear",
    "id": "ENG-101",
    "relation": "context",
    "direction": "imported",
    "sync_mode": "manual",
    "state": "in_progress"
  },
  {
    "provider": "github",
    "id": "5678",
    "relation": "derived",
    "direction": "exported",
    "sync_mode": "export",
    "parent_id": "1234",
    "state": "open"
  }
]
```

Example planner interaction summary:

- Import: select `github`, query `label:planning`, create new epics with
  `relation=primary`.
- Export: select `github`, export chosen epics, attach `direction=exported` and
  add `ext:github` labels.

## Provider integration architecture

Integration should be skill-first, with a stable core contract.

Core Atelier responsibilities:

- Canonical schema validation and storage.
- Linking semantics and readiness enforcement.
- Planner orchestration points and explicit sync controls.

Skill/provider responsibilities:

- Authentication and provider API calls.
- Provider-specific mapping logic.
- Optional pull/push sync implementations.

Default provider:

- GitHub Issues support should be available out of the box, but implemented via
  the same contract used by other providers where possible.

## Skill integration contract

Skills act as provider adapters when a first-party integration is not bundled in
Atelier. Planner calls skills with explicit payloads and expects normalized
ticket records in return.

Planner should use the `tickets` skill as the orchestration layer. It delegates
provider-specific API calls to provider skills (for example `github-issues`) and
uses `external_import`/`external_sync` to update Beads metadata.

Required skill inputs:

- `provider`: provider slug (`github`, `linear`, `jira`, `beads`, `custom`).
- `operation`: one of `import`, `export`, `link`, `sync_state`.
- `bead_ids`: list of bead ids affected by the operation.

Optional skill inputs:

- `query`: provider-specific query string for imports.
- `relation`: default relation to apply for imported or exported tickets.
- `sync_mode`: desired sync mode for new links.
- `filters`: provider-specific filters expressed as a JSON object.
- `provider_config`: provider-specific auth/config data (opaque to core).

Required skill outputs:

- `tickets`: list of normalized external ticket entries with `provider` and `id`
  set. Other canonical fields are optional but should be supplied when available
  (`url`, `relation`, `direction`, `sync_mode`, `state`, `raw_state`,
  `state_updated_at`, `parent_id`, `on_close`, `last_synced_at`).

Optional skill outputs:

- `errors`: list of per-ticket error messages for partial failures.
- `metadata`: provider-specific response metadata for audit.

Mapping rules:

- Planner validates each ticket entry using the canonical schema and merges them
  into `external_tickets`.
- Invalid entries are skipped with a visible warning; valid entries are merged
  by `(provider, id)` to avoid duplicates.

Example skill input:

```json
{
  "provider": "linear",
  "operation": "import",
  "bead_ids": ["atelier-123"],
  "query": "label:planning",
  "relation": "primary",
  "sync_mode": "import"
}
```

Example skill output:

```json
{
  "tickets": [
    {
      "provider": "linear",
      "id": "ENG-101",
      "url": "https://linear.app/org/issue/ENG-101",
      "relation": "primary",
      "direction": "imported",
      "sync_mode": "import",
      "state": "open"
    }
  ]
}
```

## Minimal provider contract

Required operations:

- `import`: fetch remote tickets and normalize records.
- `create`: create remote ticket from local bead.
- `link`: associate existing local and remote records.
- `set_in_progress`: set remote ticket to in-progress state when supported.

Optional operations:

- `update`: push selected local fields to remote.
- `create_child`: create child/split ticket where provider supports hierarchy.
- `sync_state`: refresh cached remote state for linked tickets.

Capabilities should be explicit per provider (for example: `supports_children`,
`supports_update`, `supports_state_sync`).
