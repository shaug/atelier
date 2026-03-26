# Trycycle Runtime Feasibility for Atelier

## Scope

This document evaluates whether trycycle-style implementation hardening can be
adapted to Atelier through a repo-owned `runtime profile`.

This slice is analysis and architecture guidance only. It does not ship a new
runtime mode, does not add CLI flags, and does not require a local trycycle
installation.

The analysis must keep Atelier's core intent intact: orchestrated agent
development with operator accountability.

## Source Inputs

This feasibility decision is based on:

- User requirements and constraints from the planning transcript.
- The `trycycle-planning` skill behavior model used during planning.
- Existing Atelier docs and runtime contracts, including:
  [Atelier Behavior and Design Notes], [Atelier Dogfood Golden Path],
  [Worker Runtime Architecture], and [North-Star Review Gate].
- Planner and worker template contracts in [Planner Template] and
  [Worker Template].
- Current command/runtime wiring in [Plan Command], [Work Command], and
  [Worker Prompts].
- Current skill projection and planner/worker skills in [Skills Projection],
  [Planner Startup Check], [Startup Contract], [Plan Changesets], and [Publish].

## Atelier Invariants

The feasibility decision preserves these Atelier invariants:

- Durable planning and coordination state lives in Beads.
- Planner and worker communicate through a shared message/ticket space, external
  triggers, and thread-linked updates instead of ephemeral chat.
- Worker execution is one changeset per session, then exit.
- Multiple workers can process available work concurrently.
- Pull request handling, merge/integration state, and publish/finalize behavior
  are part of worker lifecycle execution in PR-enabled projects.
- Human cognitive review load is an explicit constraint; oversized work should
  be split into reviewable changesets.
- Operator accountability remains explicit through promotion, review, publish,
  and lifecycle decisions.

## Trycycle-Derived Behaviors Under Review

The requested adaptation scope focuses on model-level behaviors from trycycle:

- Hard planning and plan-review loops before implementation.
- Explicit test strategy and test-plan checkpoints before execution.
- Iterative implementation/review/fix loops with stronger convergence pressure.
- Better runtime discipline for planner and worker behavior.

The request does not require embedding trycycle itself into Atelier. The target
is a repo-owned adaptation into an Atelier `runtime profile` if compatible.

## Observed Strengths Already Present in Atelier

Atelier already has meaningful hardening behavior:

- Planner startup discipline and deterministic startup checks.
- Explicit lifecycle contracts and durable coordination via Beads/messages.
- Worker prompt guardrails and north-star review gating before publish.
- Publish/finalize policies that tie execution to integration evidence.
- Changeset sizing and decomposition expectations for reviewability.

This baseline reduces risk for partial adaptation because the system already has
durable orchestration contracts.

## Mismatch Matrix

- Concern: Planning convergence loops Trycycle assumption: Session-local
  subagent feedback loop drives readiness. Atelier model: Planner updates
  durable Beads artifacts and explicit promotion. Compatibility: Compatible only
  with bounded adaptation.
- Concern: Testing gates Trycycle assumption: Pre-execution strategy and
  test-plan phases drive flow. Atelier model: Worker contracts and repository
  gates enforce verification. Compatibility: Compatible now as runtime-profile
  guidance.
- Concern: Implementation feedback loops Trycycle assumption: In-session
  subagent communication drives review/fix. Atelier model: Durable
  worker/planner coordination is thread-based. Compatibility: Not compatible
  without architectural change.
- Concern: Communication transport Trycycle assumption: Subagent chat is the
  primary coordination channel. Atelier model: Shared message/ticket space in
  Beads is authoritative. Compatibility: Not compatible without architectural
  change.
- Concern: Concurrency model Trycycle assumption: Local orchestration controls
  one execution lane. Atelier model: Multiple workers may process ready work
  concurrently. Compatibility: Compatible only with bounded adaptation.
- Concern: Late-phase delivery Trycycle assumption: Prompt completion is often
  the primary outcome. Atelier model: PR-driven and publish-driven lifecycle
  states are first-class. Compatibility: Compatible only with bounded
  adaptation.
- Concern: Scope control Trycycle assumption: Scope may shift in-session via
  subagent negotiation. Atelier model: Scope is constrained by beads and
  acceptance criteria. Compatibility: Compatible now as runtime-profile
  guidance.
- Concern: Oversized work handling Trycycle assumption: Split behavior is mostly
  loop-internal. Atelier model: Split behavior must preserve review-sized bead
  lineage. Compatibility: Compatible now as runtime-profile guidance.
- Concern: Accountability Trycycle assumption: Local loop quality signals are
  primary. Atelier model: Operator accountability is explicit and durable.
  Compatibility: Not compatible without architectural change.

## Feasibility Verdict

Direct trycycle-style runtime substitution is not currently feasible in
Atelier's present architecture.

The deepest mismatch is communication and orchestration shape:

- trycycle assumes subagent-heavy local convergence loops.
- Atelier assumes durable Beads/message coordination, external lifecycle
  triggers, explicit PR/publish states, and operator accountability.

This is an architectural mismatch, not a failure of Atelier. The systems
optimize for different control planes.

## Recommended Runtime Profile Cut

A narrower adaptation is feasible now as a repo-owned `runtime profile` layer:

- Repo-owned planner hardening guidance:
  - stronger plan-quality checklist before promotion,
  - explicit ambiguity closure rules,
  - deterministic readiness criteria.
- Repo-owned worker hardening guidance:
  - explicit test-strategy and verification checklists,
  - review loop evidence requirements tied to durable artifacts,
  - clearer stop/continue rules for blocked execution.
- Additive behavior only:
  - no new transport type,
  - no dependency on local trycycle installs,
  - no shared workspace identifier changes.

This cut keeps Atelier's durable orchestration model and incorporates selected
implementation-hardening behaviors.

## Required Architectural Changes

Deeper trycycle-style adaptation would need architectural work while preserving
Atelier's functional intent:

- Durable feedback-loop records in Beads/messages to represent iterative review
  and retry outcomes without ephemeral subagent chat.
- A coordinator/supervisor model that can orchestrate multi-round execution
  across planner and worker boundaries in a durable way.
- Typed Beads/message artifacts for intermediate verification, retry intent, and
  review disposition.
- Explicit contract for split negotiation when work exceeds reviewability
  thresholds during execution.
- Stronger reconciliation between PR/review/publish states and iterative
  execution loops.

These are compatible with Atelier goals, but they require intentional runtime
architecture changes instead of profile-only tweaks.

## Future Verification Floor

Any future runtime-profile implementation should meet a hybrid floor:

- Focused unit tests for selection, config precedence, environment wiring, and
  fail-closed behavior.
- One planner launch-boundary scenario test through real command surfaces.
- One worker launch-boundary scenario test through real command surfaces.

This floor gives real-surface confidence without requiring heavyweight end-to-
end infrastructure for every change.

## Recommended Follow-Up Slices

1. Add repo-owned planner/worker runtime-profile scaffolding for bounded
   hardening behaviors.
1. Design durable feedback-loop state artifacts in Beads/messages for iterative
   review/retry cycles.
1. Define a coordinator architecture proposal for deeper adaptation that keeps
   operator accountability and PR-driven lifecycle behavior.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier behavior and design notes]: ./behavior.md
[atelier dogfood golden path]: ./dogfood.md
[north-star review gate]: ./north-star-review-gate.md
[plan changesets]: ../src/atelier/skills/plan-changesets/SKILL.md
[plan command]: ../src/atelier/commands/plan.py
[planner startup check]: ../src/atelier/skills/planner-startup-check/SKILL.md
[planner template]: ../src/atelier/templates/AGENTS.planner.md.tmpl
[publish]: ../src/atelier/skills/publish/SKILL.md
[skills projection]: ../src/atelier/skills.py
[startup contract]: ../src/atelier/skills/startup-contract/SKILL.md
[work command]: ../src/atelier/commands/work.py
[worker prompts]: ../src/atelier/worker/prompts.py
[worker runtime architecture]: ./worker-runtime-architecture.md
[worker template]: ../src/atelier/templates/AGENTS.worker.md.tmpl
