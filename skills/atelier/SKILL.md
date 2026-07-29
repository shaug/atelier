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
- the compatible `agent-scripts.implement-ticket/delegated-execution/v2`
  manifest, schemas, and dependency-owned validator;
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

## Available modes

Production `plan` behavior is implemented only for one GitHub-backed assignment.
Before planning, read `references/planning.md` and follow its draft, revision,
preview, explicit operator approval, and promotion boundary. Use
`scripts/planning.py`; do not emulate a second persistence or approval path.

Production work coordination through claim, checkpoint, block, release, and
takeover is implemented. Before claiming, read `references/claiming.md`, repeat
the fail-closed host preflight, and use `scripts/claiming.py`. Never mint a
replacement fence for a stale worker or acknowledge a candidate that is not
reachable at its exact declared remote ref and head.

Production delegated implementation is implemented for one active claimed
assignment. Before delegation, read `references/delegation.md`, repeat the
fail-closed host preflight, and use `scripts/delegation.py` to prepare the exact
v2 invocation, service fresh-observation checkpoints, and validate one terminal
result. Launch one fresh worker through the host with the installed
`agent-scripts:implement-ticket` skill. Do not copy its workflow, spawn a
substitute CLI process, cache provider observations, or widen Atelier's v0
authority ceiling.

Production `audit` behavior is not implemented yet. When it is requested:

1. Report that audit is unavailable in the reset scaffold.
1. Link the owning issue: shaug/atelier#780.
1. Make no mailbox, repository, ticket, pull-request, or acceptance mutation.

An explicit host-readiness request may complete the read-only host preflight and
return its exact compatibility or failure result. That does not make audit
available.

## Mailbox boundary

The strict v1 mailbox schema and fresh-clone reconstruction helper are
implemented. Verified fast-forward canonical writes plus bounded plan and claim
coordination transitions are also implemented. Before interpreting mailbox documents, read
`references/mailbox-validation.md` and use its read-only helper.
Before persisting a transition, read `references/git-mailbox-writes.md` and use
its isolated compare-and-swap writer.

Fail closed on every unsupported schema, unknown normative field, invalid
lifecycle combination, contradictory reference, or missing external readiness
gate. The reconstructed snapshot is invocation-local and must never be written
back as a manifest, cache, index, or projection. A caller must supply fresh
operation-specific lifecycle, policy, ticket, claim, candidate, and authority
checks; the Git writer supplies persistence, not permission.

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
  missing, pre-read, stale, contradictory, or unverifiable state. Pin the
  dependency's complete delegated protocol bundle before trusting it.
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
