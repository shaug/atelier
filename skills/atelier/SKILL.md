---
name: atelier
description: >-
  Coordinate accountable software development through durable planning, bounded
  worker delegation, Git-mailbox state, live audit, and explicit operator
  acceptance. Use when the user explicitly invokes Atelier in plan, work, or
  audit mode, or asks to continue an Atelier-managed initiative across separate
  Codex tasks.
---

# Atelier

Atelier is a workflow framework for development at the speed of accountability.
It separates durable intent, delegated implementation, current evidence, and
human acceptance across agentic tasks.

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
