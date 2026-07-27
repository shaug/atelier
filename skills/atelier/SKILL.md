---
name: atelier
description: >-
  Coordinate accountable software development through durable planning, bounded
  worker delegation, Git-mailbox state, live audit, and explicit operator
  acceptance. Use when the user explicitly invokes Atelier in plan, work, or
  audit mode, asks to inspect Atelier host readiness, or asks to continue an
  Atelier-managed initiative across separate Codex tasks.
---

# Atelier

Atelier is a workflow framework for development at the speed of accountability.
It separates durable intent, delegated implementation, current evidence, and
human acceptance across agentic tasks.

## Host boundary

Codex is the v0 reference host. Before reading native project state or invoking
future delegation behavior, read `references/host-boundary.md` and complete its
fail-closed startup preflight.

The preflight must prove:

- the exact plugin-qualified `agent-scripts:implement-ticket` skill identity;
- the compatible
  `agent-scripts.implement-ticket/delegated-execution/v1` manifest, schemas, and
  dependency-owned validator;
- the six v0 candidate, pull-request, and review authority actions declared by
  the host capability descriptor;
- the installed and authorized `github@openai-curated` connector;
- every required read-only issue, relationship, pull-request, comment, review,
  check, and thread operation; and
- one complete observation conforming to
  `references/github-observation.schema.json` when live state is requested.

Run `scripts/host_boundary.py` exactly as the reference describes. Stop with its
diagnostic when any identity, operation, schema, pagination result, or
observation is missing or mismatched. Never scan for a substitute skill, use a
copied workflow, treat cached prose as native state, or cross into a provider
mutation.

## Reset scaffold

This release is the post-CLI reset scaffold. Production `plan`, `work`, and
`audit` behavior is not implemented yet. Do not emulate missing Atelier behavior
with ad hoc orchestration, hidden local state, copied Agent Scripts workflows,
or tracker mutations.

When invoked before the required mode is implemented:

1. Identify the requested mode: `plan`, `work`, or `audit`.
1. Report that the mode is unavailable in the reset scaffold.
1. Link the owning issue:
   - `plan`: shaug/atelier#777
   - `work`: shaug/atelier#778 and shaug/atelier#779
   - `audit`: shaug/atelier#780
1. Make no mailbox, repository, ticket, pull-request, or acceptance mutation.

An explicit host-readiness request may complete the read-only host preflight and
return its exact compatibility or failure result. That does not make any
production mode available.

## Invariants

Preserve these boundaries in every future mode:

- The Git mailbox is Atelier's only shared state.
- Native tickets describe project work.
- Agent Scripts remains an independently installed dependency and owns ticket
  implementation and its transitive workflow.
- Atelier owns approved intent, project policy, authority fencing, durable
  coordination, terminal validation, audit, and operator acceptance.
- Delivery is not acceptance. Acceptance is not merge, deployment, or native
  ticket completion.
- Every consequential action is bounded by current authority and fails closed on
  missing, stale, contradictory, or unverifiable state.
- Do not add Beads, Dolt, SQLite, a daemon, a server, a persistent projection,
  or backward compatibility.

## Governing contracts

Read the repository contracts before implementing a mode:

- `docs/atelier-skill-design.md`
- `docs/git-mailbox-contract.md`
- `docs/project-policy-contract.md`
- `docs/implementation-plan.md`

The native implementation graph begins at shaug/atelier#772. Treat its current
`parent`, `subIssues`, `blockedBy`, and `blocking` relationships as dependency
truth.
