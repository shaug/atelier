# Atelier as a Skill

## Next-Version Design

**Status:** Proposed direction, revised after initial adversarial review

This document defines the high-level direction for the next version of Atelier.
It is a strategic reset, not an incremental revision of the current CLI.

The [Git Mailbox Contract] defines the backing repository and the minimal
planner-worker interactions that this design relies on. The
[Atelier Project Policy Contract] defines the project-owned authority,
validation, and acceptance predicates applied to those interactions. The
[Mailbox Protocol Validation] records the disposable two-clone experiment used
to test the backing mechanism.

## Summary

Atelier will become an opinionated, host-native skill for accountable
agent-assisted development.

It will run inside capable agent hosts such as Codex and Claude Code rather than
launching, supervising, or replacing them. It will use those hosts for agent
execution, subagents, timers, permissions, worktrees, and task continuity.

Atelier will own:

- shaping intent before implementation,
- separating planning authority from implementation authority,
- promoting work through explicit human decisions,
- coordinating work across projects,
- keeping changesets cognitively reviewable,
- recording durable planner-worker communication,
- applying project-specific authority and review policy,
- separating worker delivery from accountable acceptance,
- and producing evidence that an accountable operator can accept.

Atelier will delegate implementation, review, and pull-request handling to the
independently useful [Compris] skills. The initial version does not
delegate merge, deployment, or ticket-state mutation.

A dedicated Git repository will serve as Atelier's passive planning record and
mailbox. Its human-readable documents are authoritative. Git history records
their evolution. Atelier will not require Beads, SQLite, Dolt, a background
daemon, or an Atelier server.

## Motivation

Agent hosts have absorbed most of the execution capabilities that justified the
standalone Atelier CLI:

- launching and resuming agents,
- creating isolated worktrees,
- orchestrating subagents,
- scheduling or repeating work,
- enforcing local permissions,
- loading reusable skills,
- connecting to ticket systems,
- and operating Git and pull-request workflows.

Competing with those capabilities makes Atelier responsible for a large and
rapidly changing execution surface without strengthening its central idea.

Atelier's remaining value is the idea expressed in the [Atelier North Star]:
implementation has become cheap, but trust has not. The system should optimize
for work that humans can understand, review, and take responsibility for.

The next version therefore moves Atelier up one level. It becomes a way of
thinking about and governing agentic work, not another environment in which
agents run.

## Product thesis

> Atelier enables development at the speed of accountability.

Atelier treats accountability as an engineering constraint:

- Intent exists before implementation.
- Work is approved explicitly.
- Authority is bounded and visible.
- Dependencies and sequencing are legible.
- Implementation is divided at human review boundaries.
- Scope growth becomes a decision rather than silent diff growth.
- Current-head validation and review are evidence, not implication.
- Interrupting or replacing an agent does not lose the work's context.

The workshop metaphor remains important. As [Why Atelier?] explains, a workshop
is not a factory. It values craft over automation, explicit intent over
invisible orchestration, and tools that can change without changing the work's
meaning.

## Goals

The next version should:

1. Support a general planner that can shape and coordinate work across projects.
1. Support project-specific planners when local context or governance requires
   them.
1. Support project-specific workers that claim only approved work for their
   project.
1. Preserve planner-worker communication independently of any agent task or
   native ticket system.
1. Model cross-project initiatives and dependencies.
1. Allow each project to declare its own approval, review, ticket, and
   automation policy.
1. Use native project tickets where useful or required without making them the
   only possible Atelier coordination channel.
1. Delegate implementation mechanics to Compris rather than rebuilding
   them.
1. Make every shared transition inspectable through ordinary Git and text tools.
1. Fail closed when authority, persistence, or current state cannot be
   established.

## Non-goals

The next version will not:

- launch or supervise agent processes,
- implement a general-purpose agent runtime,
- provide its own scheduler or watch loop,
- manage project worktrees,
- parse agent transcripts to recover sessions,
- replace GitHub, Linear, or another native delivery tracker,
- mirror native tickets into an Atelier issue database,
- synchronize mutable fields between ticket providers,
- own pull-request or merge mechanics,
- optimize for maximum agent utilization or code throughput,
- require every assignment to reach a solution in one agent session,
- provide multiple storage backends,
- maintain compatibility with the current Atelier CLI or data,
- or provide a hosted Atelier service.

Atelier is allowed to remain a personal, strongly opinionated workflow. General
adoption and compatibility are not design constraints.

## System boundary

```text
Operator
   |
   v
Atelier skill
   |-- planning, promotion, policy, coordination, audit
   |
   +--> Git mailbox repository
   |      durable intent, assignments, messages, claims, receipts
   |
   +--> Compris
   |      implementation, review, changeset carving, PR lifecycle
   |
   +--> Native project systems
          tickets, repositories, CI, pull requests, deployments
```

The agent host surrounds this system. It provides the active task, subagents,
permissions, timers, worktrees, connectors, and user interface. Atelier does not
persist or reproduce host task state.

Codex is the reference host for v0. Its plugin, skill, subagent, connector, and
permission surfaces define the first tested adapter. This is a delivery
constraint, not a product claim that Atelier concepts belong to Codex.

A future Claude Code adapter should preserve the same Atelier documents,
transitions, authority vocabulary, Compris contract, and mailbox history.
Only host integration may differ: command discovery, skill invocation, subagent
launch, permission prompts, and connector access. If a supposedly portable
Atelier rule must branch on host identity, the rule belongs above the host
adapter or the contract is underspecified. Claude compatibility is deferred
until the Codex reference path works; it must not distort v0.

## Distribution and dependency model

Atelier should remain its own repository and plugin. It is an application built
on Compris, not a peer skill collection inside Compris.

Compris remains independently installable and useful. It must not depend
on or contain Atelier-specific behavior.

The initial worker mode depends directly on one named Compris capability:
`implement-ticket`. That capability owns its own implementation, changeset
carving, review, pull-request, and babysitting workflow. Atelier must not
re-orchestrate its transitive skills.

Audit mode may invoke `review-code-change` directly when an independent review
of one exact candidate is itself the audit operation. The initial version does
not invoke `implement-epic`: Atelier owns its cross-project assignment graph,
while `implement-epic` owns a native ticket graph.

Where a host supports plugin dependencies, Atelier should declare an explicit,
versioned dependency. Where it does not, Atelier should perform a startup
capability check and fail with exact installation guidance. It must not silently
fall back to a bespoke implementation workflow.

The initial version will not vendor Compris. A copied dependency would
create release lag and pressure for Atelier-specific patches. Explicit
prerequisites preserve the platform/application boundary more honestly.

### Compris capability contract

Before claiming work, Atelier must establish that the host can invoke a
  compatible `compris.implement-ticket/delegated-execution/v2` capability
and validate its `capability.json` discovery manifest plus versioned invocation,
checkpoint, and result schemas. Finding a skill with the expected name is not
sufficient.

The invocation contract supplies:

- the eligible native ticket and owning tracker,
- the project repository and exact base,
- the approved Atelier work identifier, revision, and opaque approval evidence
  containing the mailbox approval commit,
- intent, scope, non-goals, constraints, and done definition,
- validation and review expectations,
- the durable authority ceiling and governing project-policy identity,
- the operator-only acceptance policy,
- the current claim and worker-run identifiers,
- the claim's last consumed checkpoint sequence and opaque continuation token,
- and a caller-provided checkpoint command.

The initial accepted outcomes are:

- `ready_pr`,
- `blocked`,
- and `requires_epic`.

`ready_pr` moves work to `delivered` only after Atelier independently verifies
the current claim, approved revision, policy, native ticket, repository, exact
remotely reachable candidate, validation, review, and pull-request state.
`blocked` produces a blocked attempt receipt. `requires_epic` returns to
planning; it does not authorize Atelier to invoke `implement-epic`
automatically. A PR stack, merge, deployment, branch deletion, or native-ticket
mutation is outside the initial Atelier authority vocabulary.

The capability must invoke the checkpoint command before every consequential
external mutation. It must also report `candidate_published` immediately after
publishing or advancing a remote candidate and receive an acknowledgement before
continuing. A denied, malformed, unknown, or unavailable checkpoint blocks
execution. If implementation state exists at a blocked terminal result, the
result must identify a durable handoff ref or state explicitly that no
transferable candidate exists. A published blocked result may have no pull
request when acknowledgement failed before PR creation; its verified candidate
is recoverable project state but becomes shared Atelier state only after a later
mailbox transition records it.

Atelier's checkpoint helper atomically compares and advances the expected
sequence and opaque continuation token in its authoritative Git transition. On
allowance, the same transition appends the invocation, phase, action, proposed
effect, candidate, and acknowledgement to the claim's authorization ledger. A
denial preserves the prior sequence and token. Before consuming any terminal
result, Atelier uses the Compris validator to require the reported
terminal sequence and token to equal the current claim-ledger tail. It then
requires the terminal `authority_used` set to equal the allowed pre-mutation
actions in that ledger; missing or extra actions block the result. A consumed
request cannot be replayed. Compris validates each exchange, but Atelier
owns durable compare-and-swap semantics and the ledger.

If capability compatibility is missing before claim, the work remains approved.
If it becomes unavailable after a claim, the worker blocks or releases the work
with an attempt receipt whenever implementation state exists. Atelier never
substitutes an inline implementation workflow.

## Skill shape

Atelier should present one entry skill with explicit modes. The host-specific
invocation may differ, but the conceptual interface is:

- `atelier plan`
- `atelier work`
- `atelier audit`

Like Trycycle, the entry skill may route to focused internal phases and
references. Unlike the current Atelier CLI, those phases orchestrate host-native
capabilities rather than implementing an agent runtime.

### What "Trycycle-like" means

Atelier should follow Trycycle's useful structural pattern:

- one explicit entry skill,
- phase-specific instructions and artifacts,
- host-native subagents rather than a proprietary worker process,
- fresh planning or review perspectives where independence matters,
- bounded refinement loops with explicit stop conditions,
- user decisions at authority boundaries,
- and deterministic helpers only where persistence or validation requires them.

The resemblance ends at the session boundary.

Trycycle is designed to drive one given effort to a solution in one agentic
session. After the initial design interaction, the operator can delegate most
implementation judgment to the agent, subject to authority overrides when its
review loops do not converge. Completion of the requested solution is the
organizing objective.

Atelier is designed for durable software work. Authority may be delegated, but
accountability remains distributed across the operator, project policy,
reviewers, maintainers, and the evidence accumulated over time. Completion is
subordinate to preserving that accountability.

An Atelier session may validly end with work blocked, released, deferred,
replanned, rejected, or waiting for a human decision. A later session or a
different worker must be able to continue from durable artifacts without
inheriting the original agent's hidden context. The Git mailbox carries that
continuity; no orchestrator process remains alive between sessions.

### Accountability chain

Atelier distinguishes the decisions that a throughput-oriented workflow can
collapse:

```text
approved contract
  -> authorized claim
  -> execution attempt
  -> exact candidate
  -> delivery with current evidence
  -> accountable acceptance
  -> accepted work
```

Approval authorizes an attempt within a durable ceiling. A claim assigns
cooperative mutation ownership. Execution produces a candidate. Delivery makes
that candidate reviewable and records evidence. Acceptance is a separate
decision that the evidence satisfies the approved contract and project policy.
Only an authorized operator may record acceptance. A worker cannot infer it from
having produced a pull request, merge, deployment, or receipt.

### Plan mode

Plan mode works with the operator to turn incomplete intent into approved,
worker-ready assignments.

It should:

1. Check unresolved planner messages and delivered work awaiting acceptance.
1. Present each delivered candidate, approved contract, and live evidence for an
   operator acceptance or rework decision.
1. Record acceptance only when the invoking operator is authorized to accept it.
1. Capture a concrete idea as draft work without requiring approval.
1. Record intent, rationale, non-goals, constraints, edge cases, related
   context, and a done definition.
1. Identify affected projects and cross-project dependencies.
1. Decompose work only where sequencing, independence, or reviewability
   benefits.
1. Challenge ambiguous scope and missing negative requirements.
1. Preview the complete proposed initiative and its assignments.
1. Ask the operator to approve promotion.
1. Record the exact approved revision, durable authority ceiling, acceptance
   policy, and governing project-policy revision.
1. Link one existing eligible native ticket. Initial plan mode never creates or
   mutates native tickets.

Drafting and approval are distinct. Agents may create and improve drafts freely.
Approval is an authority transition.

### Work mode

Work mode runs in the context of one project.

It should:

1. Resolve the current project and its policy.
1. Fetch the Git mailbox and check work-threaded messages.
1. Identify approved work whose dependencies and project-specific gates are
   satisfied.
1. Verify that the required Compris capability and native ticket are
   available.
1. Refuse a claim while another assignment for the project is active.
1. Claim exactly one assignment through a verified Git transition.
1. Confirm the approved assignment revision, policy identity, current claim, and
   effective authority.
1. Delegate implementation to `implement-ticket`.
1. Register the exact candidate when durable implementation state first exists.
1. Post questions, blockers, discoveries, and scope-change requests to the
   assignment's durable thread.
1. Reject material unapproved scope growth.
1. Revalidate the claim before every consequential external mutation.
1. Record an attempt receipt for blocked, released, or delivered work using
   exact candidate, validation, review, and pull-request evidence.
1. Deliver accountable work into `delivered`, or leave the assignment blocked or
   released through another verified Git transition.

Initial work mode is serial: a project may have only one active assignment.
Parallel assignment execution is outside v0.

Finishing the assignment in the invoking session is not a success condition. A
worker succeeds when it either produces accountable evidence for the approved
outcome or leaves the work in an explicit, truthful, recoverable state.

### Audit mode

Audit mode is read-only. It reconstructs accountability from the Git mailbox and
live project systems.

Each audited promise receives one explicit verdict:

- `satisfied`,
- `violated`,
- `unknown` because required evidence is unavailable,
- `stale` because the candidate or governing state changed,
- `needs-decision`,
- or `authority-unreconstructable`.

Audit should identify:

- approved work with no implementation,
- active work whose claim or approved revision is unclear,
- implementation that exceeds its approved scope,
- unresolved planner-worker decisions,
- stale pull-request or review evidence,
- missing validation or required review,
- delivered work awaiting acceptance,
- accepted work whose evidence has since become stale or unavailable,
- and actions that exceed project policy or task-specific authority.

Audit reads live native state when that state is part of the evidence. Cached or
historical success is not sufficient.

## Planning model

The initial model should remain deliberately small.

### Initiative

An initiative is an optional, non-authoritative grouping document for a coherent
outcome that may span projects. It explains cross-project intent. Children are
derived only from each assignment's `initiative_id`; executable authority,
dependencies, readiness, and acceptance belong to assignments. Initiative
progress is derived from those children.

### Assignment

An assignment is one project-scoped unit of approved work that a worker may
claim. It should be independently understandable and reviewable.

An initiative whose scope already fits one project and one reviewable changeset
may consist of a single assignment. Atelier should not require ceremonial
one-child decomposition.

### Message

A message is durable communication attached to an assignment. The work, not the
agent task, is its address.

### Receipt

A receipt records the evidence produced by one execution attempt. It should
identify:

- whether the attempt blocked, released, or delivered,
- the approved assignment revision,
- the worker claim,
- the project and exact candidate revision,
- the candidate branch and pull request when durable implementation exists,
- validation performed and its outcome,
- independent review performed and its outcome,
- the native ticket and pull request when present,
- unresolved obligations,
- and whether mutation ownership was retained or relinquished.

Receipts summarize evidence; they do not replace live verification.

## Human-shaped changesets

Cognitive-shaping doctrine — the mental-model standard, its calibrating scale,
and the eight breakdown rules — is owned by compris, not Atelier. Atelier does
not maintain a competing copy; planning judgment for shaping an initiative into
reviewable assignments defers to the [Compris Cognitive Shaping Doctrine],
published at compris commit `5c45cd2b9b9137f985b9e5e9d343894553efc1cd`
(shaug/compris#208).

## Project policy and authority

Each project carries the strict, human-readable policy defined by the
[Atelier Project Policy Contract]. Unknown fields, unsupported values, and
unreadable policy revisions fail closed.

The effective authority is the intersection of:

1. project policy,
1. the approved assignment,
1. the operator's task-specific grant,
1. and host or native-system enforcement.

A promoted assignment records its inheritable authority ceiling and the exact
repository, commit, and path of the project policy used for approval. A
task-specific operator grant is inheritable only when it is recorded in that
approved contract.

Before claim, every consequential external mutation, delivery, and acceptance,
Atelier reads the approved policy revision and current project policy. Current
policy may tighten approved authority and block an action. A later, looser
policy does not widen an existing approval; widening authority requires a new
work revision and approval. If either policy identity cannot be read or
reconciled, Atelier stops.

A skill is not a security boundary. Atelier records and checks authority, while
host permissions, protected branches, hooks, and native access controls enforce
what they can.

At approval, Atelier resolves the policy to an exact repository commit and
stores that identity and the granted subset of its authority in the work
contract. Host-local credentials and checkout paths are not policy. Work mode
verifies that the current repository matches the stable project record before it
reads or claims work.

## Relationship to native tickets

Atelier work and native project tickets have different responsibilities.

Atelier owns:

- cross-project intent,
- approval,
- assignment,
- planner-worker communication,
- and accountability receipts.

Native systems own their normal delivery and governance records.

Planning may begin privately in Atelier before a native ticket exists. The
initial worker contract, however, requires one linked and eligible native ticket
before claim because `implement-ticket` is the only direct implementation
capability.

An operator or the project's external triage process must supply that ticket;
initial plan mode never publishes one. Atelier-only execution and read-only
external-ticket execution remain unsupported until Compris offers a
generally useful ticket-independent implementation contract.

Atelier links these records; it does not synchronize mutable ticket fields or
pretend that they are the same object.

Native ticket state is checked again before repository, pull-request, or review
mutations, delivery, and acceptance. If an external edit, closure, or rejection
invalidates eligibility or the approved contract, the worker stops and records a
blocked attempt with the conflict. Atelier never resolves the disagreement by
silently copying one record over the other.

## Git mailbox

The Git mailbox is the only Atelier coordination store. It is:

- passive,
- document-based,
- human-readable,
- historically inspectable,
- independent of any managed project,
- and accessible to general and project-specific planners and workers.

It is not a task queue or notification service. Participants discover new state
when they explicitly fetch and inspect it.

The [Git Mailbox Contract] defines its repository layout, document conventions,
write protocol, claim behavior, failure semantics, and minimal interactions.

## Reliability model

Atelier deliberately accepts Git's passive availability model.

- Local drafts may exist before publication.
- Shared authority exists only after a successful, verified push.
- A remote failure blocks claims, approval, delivery, acceptance, and other
  authoritative shared transitions.
- Ambiguous push results must be read back before they are retried or reported.
- Non-fast-forward rejection requires fresh state and precondition evaluation.
- Claims do not expire automatically.
- No background service repairs or reconciles the repository.

Atelier should prefer an explicit unknown outcome over inferred success.

## What is retained

Very little current implementation should survive unchanged.

### Retain as product doctrine

- The [Atelier North Star].
- The workshop metaphor in [Why Atelier?].
- Intent before execution.
- Draft work before explicit promotion.
- Full-plan preview before approval.
- Human-shaped changeset planning.
- Visible dependencies and deliberate sequencing.
- Work-threaded rather than agent-threaded communication.
- Project-specific authority and review posture.
- Fail-closed persistence and current-state verification.

### Re-author as skills, schemas, or evaluations

- Draft creation and refinement behavior.
- Promotion and clarification behavior.
- Changeset shaping and re-split judgment.
- Planner and worker startup checks.
- Work-threaded message behavior.
- Read-only accountability status and audit behavior.
- Representative current test scenarios that express these product rules.

The existing skill text may be useful source material, but new skills should be
written for the new product boundary rather than mechanically ported.

### Abandon

- The Typer CLI as the primary product.
- Beads and Dolt integration.
- The Atelier store abstraction and migration layers.
- Agent launch, session discovery, and transcript resumption.
- Worktree creation and mapping.
- Worker runtime, hooks, watch loops, and reconciliation.
- Projected skill homes and bootstrap repair.
- GitHub and external-provider client abstractions.
- Native-ticket import, export, and mutable synchronization.
- Pull-request publication, restacking, and merge implementation.
- System/user configuration compatibility.
- Data migration and backward compatibility.
- Tests whose only purpose is preserving abandoned machinery.

The current codebase should be treated as research evidence, not as an
implementation foundation.

## Transition from the current codebase

The current CLI receives the annotated archival tag `atelier-cli-v2-final`
before the reset. The tag names the exact final legacy commit and explains that
the skill-based product supersedes it. The next implementation then replaces the
CLI rather than coexisting with it.

The tag, legacy-ticket disposition, and implementation removal are a deliberate
reset gate. Before crossing it, the composition spike must prove that an
independently installed Compris capability can be discovered, validated,
invoked with allowed and denied checkpoints, acknowledge a published candidate,
and return a valid terminal result without Atelier copying its workflow. The
operator reviews that evidence and explicitly confirms the reset a second time.

Only after that confirmation should obsolete tickets be closed as `cancelled` or
`superseded`, the archival tag be pushed, and the legacy implementation be
removed. A ticket is not `completed` merely because its architecture was
abandoned. The disposition record must map retained product obligations to the
new implementation graph before deletion begins.

There is no dual-running period, data migration, compatibility adapter, or
attempt to route new skill behavior through the existing store and worker
runtime. Existing documents and skills are source material; selected behavioral
tests may become forward-evaluation cases. Legacy Python modules and their
implementation-specific tests are not the scaffold for the new product.

This clean break is intentional. Maintaining both architectures would preserve
the infrastructure burden that the reset is meant to remove.

## Validation strategy

Atelier itself is the first low-risk live dogfood repository. It should exercise
planning, delegated implementation, review, delivery, operator acceptance, and
the reset changes while the legacy implementation remains recoverable by tag.
This proves that the workflow can govern real work, not that it generalizes.

External validation must follow before claiming broader product success. At
minimum, forward evaluations should cover:

1. A personal GitHub project with human approval and merge.
1. A cross-project initiative spanning Tuber and Peeler.
1. A corporate project where Atelier cannot create or modify native tickets.
1. Two workers racing to claim the same assignment.
1. Planner and worker messages crossing while both are active.
1. A worker discovering scope that invalidates the approved plan.
1. An interrupted worker being replaced without losing durable context.
1. Git remote failure before, during, and after a push.
1. A pull request whose previously reviewed head becomes stale.
1. Acceptance where some evidence is missing or cannot be verified.
1. Project policy changing after approval.
1. A native ticket changing or closing during execution.

Evaluations should measure:

- whether promoted assignments are self-contained,
- whether changes remain cognitively reviewable,
- whether authority boundaries are respected,
- whether interruption and resumption use durable artifacts,
- whether current evidence supports every delivery and acceptance claim,
- and how much operator effort is required to understand and accept the work.

Lines of code and raw ticket throughput are not success measures.

The backing protocol has separately passed the 16-scenario
[Mailbox Protocol Validation]. That result validates the Git mechanics, not the
future skill prompts, host integration, or live provider adapters.

## Initial delivery boundary

The first usable version should contain only:

- the Atelier entry skill,
- plan, work, and audit mode instructions,
- deterministic local Git mailbox helpers,
- the mailbox document schemas,
- the normative lifecycle and transition contracts,
- the strict project policy and evidence contract,
- the `implement-ticket` capability and result contract,
- and forward evaluations for the core planner-worker interactions.

It should support one Git mailbox realm and one native ticket provider first.
Additional providers should be expressed through host connectors and
project-policy references rather than a new Atelier provider framework. The
ordered changesets and reset gate are defined in the
[Atelier Skill Implementation Plan].

## Decisions intentionally deferred

- Exact cross-host plugin dependency packaging.
- Ticket-independent execution.
- How a planner aggregates multiple mailbox realms across trust boundaries.
- Automatic policy acceptance.
- PR stacks, integration, merge, deployment, and ticket-state mutation.
- Whether accepted work ever needs an explicit archival convention.

These decisions do not require a storage abstraction or server design.

<!-- inline reference link definitions. please keep alphabetized -->

[compris]: https://github.com/shaug/compris
[atelier north star]: ./north-star.md
[atelier project policy contract]: ./project-policy-contract.md
[atelier skill implementation plan]: ./implementation-plan.md
[compris cognitive shaping doctrine]: https://github.com/shaug/compris/blob/5c45cd2b9b9137f985b9e5e9d343894553efc1cd/docs/cognitive-shaping-doctrine.md
[git mailbox contract]: ./git-mailbox-contract.md
[mailbox protocol validation]: ./mailbox-protocol-validation.md
[why atelier?]: ./atelier-name.md
