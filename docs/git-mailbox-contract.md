# Git Mailbox Contract

## Purpose

The Git mailbox is Atelier's durable planning record and communication
mechanism.

It supports a general planner, project-specific planners, and project-specific
workers without requiring a database, daemon, hosted service, or a project's
native ticket system.

The mailbox is intentionally passive. Participants publish durable documents and
discover them when they next fetch and inspect the repository.

This document defines the initial repository conventions and the minimal
planner-worker interactions required by [Atelier as a Skill].

## Core properties

The mailbox is:

- a dedicated Git repository,
- scoped to one trust realm,
- authoritative on one canonical branch,
- composed of human-readable Markdown and YAML,
- historically explained by ordinary Git commits,
- written through fast-forward-only transitions,
- usable without an Atelier server,
- and durable across the end, failure, or replacement of any agent session.

The mailbox is not:

- a message bus,
- a task queue,
- a notification service,
- a scheduler,
- a projection of native project tickets,
- or one implementation behind a generic storage interface.

It is a small document record store with structured authoritative state. Its
boundary is concrete: it has no event projection, query service, persistent
index, alternate backend, or server process.

## Trust realms

One mailbox repository represents one trust realm.

Projects may share a mailbox only when its operators and workers may see the
names, intent, dependencies, messages, native links, and timing of all included
work.

Personal, employer, and client work should normally use separate mailbox
repositories. Atelier must not copy content between realms implicitly.

A planner may read more than one realm only when it is independently authorized
to access each repository. Cross-realm planning is outside the initial contract.

## Canonical state

The remote canonical branch, normally `main`, is the shared source of truth.

Local documents that have not been pushed are drafts. They do not establish a
shared approval, claim, decision, delivery, or acceptance.

The current tree describes current state. Git history explains how that state
changed. Consumers should not need a separate event database to understand the
mailbox.

No agent session owns a work item's lifecycle. A session may leave work active,
blocked, released, awaiting a decision, or delivered. The durable documents,
rather than the originating transcript, define what another planner or worker
inherits.

Force pushes and history rewrites are prohibited. Where the Git host supports
it, the canonical branch should reject force pushes and deletion.

## Repository layout

The initial repository layout is:

```text
atelier.yaml
projects/
  <project-id>/
    project.md
initiatives/
  <initiative-id>/
    initiative.md
work/
  <work-id>/
    work.md
    messages/
      <message-id>.md
    receipts/
      <receipt-id>.md
```

All identifiers are stable and treated as opaque by consumers. Create
identifiers use a type prefix and lowercase UUIDv7, such as `wrk_019f9a9e-...`.
The initial prefixes are `prj`, `ini`, `wrk`, `msg`, `clm`, `run`, and `rcp`. A
generated identifier that already exists with different content is a collision
and fails closed; it is never regenerated during an ambiguous retry. Renaming a
title or moving a project checkout must not change an identifier.

The initial contract does not use long-lived branches for message classes,
projects, or lifecycle states. The canonical branch is the serialization point
for shared writes. Local implementation branches are not mailbox branches, but
their remote candidate identities may appear in claims and receipts.

The initial contract neither creates nor reads Atelier tags. Commits and
documents are the only authoritative Git objects.

## Root manifest

`atelier.yaml` identifies the repository as an Atelier mailbox.

Its complete initial schema is:

```yaml
schema: atelier.mailbox/v1
realm_id: personal
canonical_branch: main
```

Unknown fields are invalid in every v1 structured document. This keeps authority
and lifecycle interpretation identical across independently evolving clients.

The manifest must not contain credentials or provider tokens.

## Project document

`projects/<project-id>/project.md` identifies a project known to the mailbox.

Its normative frontmatter is:

```yaml
---
schema: atelier.project/v1
id: prj_019f9a9e-0000-7000-8000-000000000001
name: Example Project
repository: github:example/project
policy:
  repository: github:example/project
  path: .atelier/policy.yaml
native_ticket:
  provider: github
  required_before_claim: true
status: active
---
```

The body may explain project-specific context that a general planner needs.

Machine-local checkout paths do not belong in shared mailbox documents. The host
resolves its current checkout independently. Repository identity and the stable
project identifier survive worktrees, clones, and path changes.

For work mode, project policy supplies the mailbox remote, realm identifier,
canonical branch, and stable project identifier. The worker fetches that remote
and verifies that this project document names the current repository and policy
path. Credentials remain host-local. A general planner starts from an explicitly
selected mailbox remote rather than searching for mailboxes.

## Initiative document

`initiatives/<initiative-id>/initiative.md` optionally describes a coherent
outcome that may span projects. It is non-authoritative: it grants no execution
authority and has no independent lifecycle or approval.

Its normative frontmatter is:

```yaml
---
schema: atelier.initiative/v1
id: ini_019f9a9e-0000-7000-8000-000000000001
title: Example cross-project outcome
---
```

Its body should record:

- intent,
- rationale,
- non-goals,
- constraints,
- edge cases,
- related context,
- and the initiative-level outcome.

Initiative children and progress are derived from each work document's
`initiative_id`. The initiative does not duplicate a mutable child list. A
single-assignment effort does not require a ceremonial initiative.

## Work document

`work/<work-id>/work.md` describes one project-scoped assignment.

Its normative frontmatter shape is:

```yaml
---
schema: atelier.work/v1
id: wrk_019f9a9e-0000-7000-8000-000000000001
title: Add the example behavior
project_id: prj_019f9a9e-0000-7000-8000-000000000001
initiative_id: null
status: draft
revision: 1
dependencies: []
replaces: []
native_ticket:
  provider: github
  id: "123"
  url: https://github.com/example/project/issues/123
approval: null
claim: null
blocking_message_id: null
attempt_receipt_id: null
delivery_receipt_id: null
acceptance: null
---
```

An approved work document replaces `approval: null` with:

```yaml
approval:
  approved_by: operator
  approved_at: 2026-07-25T12:00:00Z
  revision: 1
  policy:
    repository: github:example/project
    commit: 0123456789abcdef0123456789abcdef01234567
    path: .atelier/policy.yaml
  authority_ceiling:
    - repository.candidate.create
    - repository.candidate.push
    - pull_request.create
    - pull_request.update
  acceptance:
    mode: operator
    required_evidence:
      - candidate-remote-reachable
      - pull-request-head-current
      - pull-request-open
      - pull-request-mergeable
      - required-checks-pass
      - required-validation-reported
      - independent-review-current
      - unresolved-feedback-zero
```

`acceptance.mode` is always `operator` in v1. The approval commit is the
canonical commit that first contains this approved document; it is recorded by
the later claim rather than self-referenced here.

Its body should contain the worker-ready contract:

- intent,
- rationale,
- scope,
- non-goals,
- constraints,
- edge cases,
- related context,
- done definition,
- verification expectations,
- changeset or review-shape guidance,
- and explicit re-split triggers when relevant.

Shared initiative context may be referenced rather than duplicated, but an
assignment and its referenced context must be sufficient for a new worker to
understand the work without a planner transcript.

Every field shown above is required, including fields whose value is `null` or
an empty list. This makes document shape independent of lifecycle state.
`native_ticket` may remain `null` while private planning or external triage is
underway, but claim requires the complete eligible native-ticket shape.

## Lifecycle

The initial work lifecycle is deliberately small:

```text
draft -> approved -> active -> delivered -> accepted
  |          ^          |  ^       |
  |          |          |  +-------+ rework
  |          |          +-> blocked -> active
  |          +------------- release
  +-> deferred
  +-> cancelled
```

The allowed states are:

- `draft`: editable planning material with no execution authority.
- `approved`: explicitly promoted and available when its gates are satisfied.
- `active`: claimed by one worker run.
- `blocked`: claimed work that cannot continue without a recorded decision or
  dependency.
- `delivered`: an exact remotely reachable candidate and delivery receipt are
  ready for an authorized operator acceptance decision.
- `accepted`: terminal Atelier work whose delivery an authorized operator
  accepted against current evidence.
- `deferred`: intentionally unavailable until a later planning decision.
- `cancelled`: terminal work that should not be executed.

Claiming moves work from `approved` to `active`. Blocking retains the claim;
resolving the blocker returns the work to `active`. Explicit release clears the
claim and returns the work to `approved`. Delivery retains the claim, records
the exact receipt, and moves `active` work to `delivered`. Acceptance verifies
live evidence, records the accepting operator, clears the claim, and moves work
to `accepted`.

Requested rework returns `delivered` work to `active` only when the current
claim will continue. Otherwise the operator takes over or releases the claim
first. Deferring or cancelling claimed work requires release or takeover.
Replanning or splitting claimed work also requires an attempt receipt whenever
candidate state exists, then release or takeover, cancellation of the old work
with replacement links, and separately approved replacement work. `release`,
`rework`, `replanned`, and `superseded` are recorded transition or decision
outcomes rather than additional lifecycle states.

Lifecycle fields obey these invariants:

- `draft` has no approval, claim, blocker, attempt receipt, delivery, or
  acceptance;
- `approved` has approval but no claim, blocker, delivery, or acceptance; it may
  point to the latest released attempt receipt;
- `active` has approval and claim but no blocker, delivery, or acceptance; it
  may retain the latest attempt receipt while continuing a transferred
  candidate;
- `blocked` has approval, claim, one blocking message, and its blocked attempt
  receipt but no delivery or acceptance;
- `delivered` has approval, claim, exact remotely reachable candidate, and one
  receipt referenced as both the current attempt and delivery, but no
  acceptance;
- `accepted` has approval, the same attempt and delivery receipt, and
  acceptance, and no current claim or blocker;
- `deferred` and `cancelled` have no current claim or blocker, while retaining
  any prior approval, attempt receipt, and replacement links for explanation.

`attempt_receipt_id` is the canonical pointer to the latest execution outcome
that a fresh worker should inspect. Release clears the current claim, blocker,
delivery pointer, and acceptance pointer, but atomically sets
`attempt_receipt_id` to the released receipt when an attempt or candidate
exists. It never deletes messages or receipts. Returning a rejected delivery to
active clears its delivery pointer but preserves the rejected receipt as the
current attempt and preserves the decision message.

Readiness is derived, not stored. Work is ready when:

- its status is `approved`,
- its dependencies are `accepted`,
- its project policy gates are satisfied,
- its linked native ticket is live and eligible,
- a compatible `implement-ticket` capability is available,
- and it has no active claim.

## Revisions and approval

Substantive planning changes increment the work revision. Initiative edits are
ordinary explanatory commits and cannot alter approved child work implicitly.

Approval records:

- approving operator,
- approved revision,
- approval timestamp,
- exact project-policy repository, commit, and path,
- inheritable authority ceiling,
- operator-only acceptance mode,
- and evidence required for acceptance.

The canonical commit containing that transition is the exact approved artifact;
it does not need to be duplicated inside its own document.

Editing the intent, scope, non-goals, constraints, done definition,
dependencies, project assignment, or required verification of approved work
invalidates that approval. The document returns to `draft` until it is previewed
and approved again. Active, blocked, or delivered work must first be released or
explicitly taken over; a planner cannot revise the contract beneath its current
worker or accepter.

Typographical or non-semantic corrections may retain approval only when the
commit records why the approved contract did not change.

A worker claim records the exact approved revision and canonical commit that the
worker intends to execute.

The approved policy revision remains the authority ceiling for that work. Before
claim, each consequential external mutation, delivery, and acceptance, the actor
also reads current project policy:

- a stricter current policy narrows effective authority and may block the
  operation;
- a looser current policy does not widen the approved authority ceiling;
- widening authority requires a substantive revision and new approval;
- and an unavailable or incompatible policy revision stops the operation.

An operator instruction delivered only in a host transcript may narrow the
current invocation. It cannot widen authority inherited by a later session
unless it becomes part of a newly approved work revision.

## Claims

A claim coordinates cooperative mutation ownership; it is not a security lock.

Its normative shape inside `work.md` is:

```yaml
claim:
  id: clm_019f9a9e-0000-7000-8000-000000000001
  worker_run_id: run_019f9a9e-0000-7000-8000-000000000001
  work_revision: 1
  approved_commit: 0123456789abcdef0123456789abcdef01234567
  policy_commit: 0123456789abcdef0123456789abcdef01234567
  ticket_observation_digest: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  claimed_at: 2026-07-25T12:05:00Z
  host: codex
  checkpoint:
    sequence: 0
    continuation_token: opaque-token-0
    authorizations: []
  candidate: null
```

Every entry in `checkpoint.authorizations` has this complete shape:

```yaml
sequence: 1
invocation_id: run_019f9a9e-0000-7000-8000-000000000001
phase: pre_external_mutation
action: repository.candidate.create
proposed_effect_digest: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
candidate_head: null
acknowledged_candidate_head: null
recorded_at: 2026-07-25T12:06:00Z
```

`phase` is `pre_external_mutation` or `candidate_published`; `action` uses the
Agent Scripts v1 vocabulary. SHA fields are exact candidate revisions or `null`
when the action has no candidate. All other fields are required. Entries are in
strictly increasing sequence order and are append-only. When transferable
implementation state first exists, the worker updates the claim only after
publishing and verifying it:

```yaml
candidate:
  repository: github:example/project
  remote: origin
  remote_url: git@github.com:example/project.git
  remote_ref: refs/heads/scott/example-work
  base_revision: 1111111111111111111111111111111111111111
  head_revision: 2222222222222222222222222222222222222222
  pull_request: null
  workspace_id: null
  published_at: 2026-07-25T12:20:00Z
```

`workspace_id` may name a durable host workspace or task but must not contain a
machine-local path. The candidate is valid only when `head_revision` is
reachable from `remote_ref` on the verified declared remote. A local-only SHA,
an unverified push, or a mutable branch name without the exact remote ref and
head is not a candidate.

After every candidate push, the worker verifies remote reachability, publishes
the new exact head in the claim, and verifies that mailbox transition before
relying on that candidate for review, delivery, or another external mutation.

Claims do not expire automatically.

Each delegated-execution checkpoint is a verified mailbox transition. A
pre-mutation request must name the current claim, sequence, and continuation
token. Atelier fetches and reevaluates current claim, revision, policy, ticket,
candidate, and authority. On allowance, one atomic commit increments `sequence`,
rotates `continuation_token`, and appends an authorization entry containing the
invocation ID, phase, action, proposed-effect digest, exact candidate head,
acknowledged candidate head, and recorded time. Atelier pushes and reads that
exact checkpoint back before returning `allow`. Denial echoes the prior token
and does not advance the checkpoint or ledger. A consumed sequence or token
cannot be replayed, and the ledger is never truncated or rewritten.

`candidate_published` uses the same compare-and-swap transition while also
recording the exact remotely reachable candidate. An unavailable or ambiguous
mailbox outcome does not acknowledge the candidate. Before accepting any
terminal result, Atelier requires its sequence and continuation token to equal
the current claim-ledger tail. It also requires the terminal `authority_used`
set to equal the allowed `pre_external_mutation` actions in that ledger; either
under-reporting or an unrecorded action blocks the result.

A worker releases a claim explicitly when it stops without delivering the work.
An operator or planner may perform an explicit takeover when the prior worker
cannot release it. Release atomically publishes and points to the authoritative
attempt receipt. A later claim reads that pointer and adopts its verified
transferable candidate when one exists. The takeover commit must identify the
replaced claim, record a reason, and copy the exact verified candidate into the
new claim when the replaced claim has one. A takeover never silently discards a
candidate: when no transferable handoff exists it preserves and references the
current attempt receipt explaining that fact. A takeover creates a new claim
identifier and worker-run identifier; it never edits the old identifiers in
history.

Two workers may race to claim the same approved work locally. Only the worker
whose commit first advances the canonical remote branch owns the claim. Every
other worker must fetch, observe the winning claim, and stop.

A worker must fetch and verify its exact claim identifier, approved revision,
approval commit, policy identity, and effective authority immediately before:

- the first implementation mutation,
- every candidate branch push,
- pull-request creation or update,
- review reply or resolution,
- and delivery.

Unavailable or mismatched verification stops the external action. This is
cooperative fencing; host, repository, and native-system controls remain the
enforcement boundary. A takeover therefore revokes the old worker's cooperative
authority at its next mandatory fence.

Operator acceptance performs the same fresh verification independently.
Native-ticket mutation, merge, deployment, and branch deletion are unsupported
in v0 rather than merely unchecked.

## Messages

Durable messages attach to the work item they concern and live at
`work/<work-id>/messages/<message-id>.md`. Initiative-level discussion becomes
work guidance or remains planning prose; v0 does not create a second message
address.

Their normative frontmatter is:

```yaml
---
schema: atelier.message/v1
id: msg_019f9a9e-0000-7000-8000-000000000001
work_id: wrk_019f9a9e-0000-7000-8000-000000000001
kind: needs-decision
author_role: worker
worker_run_id: run_019f9a9e-0000-7000-8000-000000000001
audience: planner
in_reply_to: null
resolves: null
blocks: worker
created_at: 2026-07-25T12:30:00Z
subject: Choose the compatibility boundary
---
```

The initial message kinds are:

- `instruction`,
- `needs-decision`,
- and `notification`.

More specific meaning belongs in the subject and body until repeated use proves
that another machine-readable kind is necessary.

Messages are appended rather than edited. Corrections, answers, acknowledgments,
and resolutions are new messages that reference the earlier message.

Blocking and resolution are atomic operations:

- `block` creates exactly one unresolved `needs-decision` or `notification`
  message with `blocks: worker`, changes work to `blocked`, and stores that
  message identifier in `blocking_message_id` in one commit;
- blocked work is valid only when that referenced message exists, belongs to the
  work, blocks the worker, and has no resolving message;
- `resolve` appends one message whose `resolves` field names the blocker, clears
  `blocking_message_id`, and moves work to `active` in the same commit;
- resolving an already resolved message, or a message other than the work's
  current blocker, fails its precondition.

A non-blocking decision message does not change work status. An unresolved
message is one for which no valid later message has a matching `resolves`
reference.

Release, defer, cancel, takeover, and replacement are separate transitions with
their own authority, receipt, and claim preconditions. They cannot be smuggled
through blocker resolution.

Agent identifiers may help explain authorship but are not durable addresses. The
owning work thread and intended role are the coordination path.

## Receipts

`work/<work-id>/receipts/<receipt-id>.md` records one execution outcome.

Its normative frontmatter is:

```yaml
---
schema: atelier.receipt/v1
id: rcp_019f9a9e-0000-7000-8000-000000000001
work_id: wrk_019f9a9e-0000-7000-8000-000000000001
outcome: delivered
approved_revision: 1
approved_commit: 0123456789abcdef0123456789abcdef01234567
policy_commit: 0123456789abcdef0123456789abcdef01234567
claim_id: clm_019f9a9e-0000-7000-8000-000000000001
worker_run_id: run_019f9a9e-0000-7000-8000-000000000001
candidate:
  repository: github:example/project
  remote: origin
  remote_url: git@github.com:example/project.git
  remote_ref: refs/heads/scott/example-work
  base_revision: 1111111111111111111111111111111111111111
  head_revision: 2222222222222222222222222222222222222222
  pull_request: https://github.com/example/project/pull/456
  workspace_id: null
  published_at: 2026-07-25T12:20:00Z
handoff: transferable
native_ticket:
  provider: github
  id: "123"
validation:
  - command: just test
    outcome: passed
    candidate_revision: 2222222222222222222222222222222222222222
    observed_at: 2026-07-25T12:45:00Z
reviews:
  - mechanism: review-code-change
    verdict: clean
    candidate_revision: 2222222222222222222222222222222222222222
    comparison_base_revision: 1111111111111111111111111111111111111111
    observed_at: 2026-07-25T12:55:00Z
unresolved_obligations: []
mutation_ownership: retained
ended_at: 2026-07-25T13:00:00Z
---
```

`outcome` is `blocked`, `released`, or `delivered`. `mutation_ownership` is
`retained` or `relinquished`. A worker session ending after durable
implementation state exists must append a receipt even when it does not deliver.
The work document atomically sets `attempt_receipt_id` to that receipt so a
fresh worker never has to infer the current handoff from timestamps or
filenames. A released receipt relinquishes mutation ownership. A blocked receipt
normally retains it until release or takeover.

`handoff` is `transferable` or `none`. `candidate` is non-null exactly when the
handoff is transferable. When implementation exists but could not be published
under effective authority, a blocked receipt uses `handoff: none` and explains
why. A delivered receipt requires a remotely reachable candidate, evidence
satisfying the approved delivery policy, exactly one open pull request for that
candidate, and `mutation_ownership: retained` until acceptance, release, or
takeover. V1 cannot encode a PR stack or merged result.

Validation entries identify the command, outcome, exact candidate revision, and
observation time. Review entries identify the reviewer or review mechanism,
shared review verdict (`clean`, `changes_required`, or `blocked`), exact
candidate and comparison-base revisions, and observation time. A review can
satisfy `independent-review-current` only when its verdict is `clean` and its
candidate and comparison-base revisions match the current delivery. Findings
retained by a clean shared review keep their recorded dispositions; Atelier does
not reinterpret an explicit deferral as a gating failure. The body explains
discoveries, unresolved obligations, handoff instructions, and the next required
decision.

Receipts are concise evidence indexes. Audit mode must read live native state
when current state matters.

Acceptance is stored in `work.md` and references one delivered receipt:

```yaml
acceptance:
  receipt_id: rcp_019f9a9e-0000-7000-8000-000000000001
  accepted_by: operator
  accepted_at: 2026-07-25T13:15:00Z
  policy_commit: 0123456789abcdef0123456789abcdef01234567
  candidate_revision: 2222222222222222222222222222222222222222
  evidence:
    candidate-remote-reachable: satisfied
    pull-request-head-current: satisfied
    pull-request-open: satisfied
    pull-request-mergeable: satisfied
    required-checks-pass: satisfied
    required-validation-reported: satisfied
    independent-review-current: satisfied
    unresolved-feedback-zero: satisfied
```

Acceptance records what was verified at that commit. If evidence later becomes
unavailable, stale, or contradictory, history is not rewritten. Audit reports
the current promise as `unknown`, `stale`, or `violated` and cites the earlier
acceptance.

## Minimal planner-worker interactions

The mailbox initially supports only these durable interactions:

- A planner creates or revises a draft work document.
- An operator approves a revision and authority envelope.
- A worker claims approved work and registers its exact candidate.
- A planner sends work-threaded guidance.
- A worker requests a decision or reports a discovery.
- A planner or operator resolves a decision with a lifecycle transition.
- A worker blocks with a message and attempt receipt.
- A worker releases with a receipt and returns work to approved.
- An operator or planner takes over with a replacement claim and rationale.
- A worker delivers with a receipt into `delivered`.
- An authorized operator accepts the delivery into `accepted`.
- A planner defers, cancels, or replaces work explicitly.

There is no durable agent-to-agent message that lacks an owning work item. A
transient host task may report that no eligible work exists, but that fact does
not create mailbox content.

## Normative transition contract

Every transition uses the common write protocol plus these semantic
preconditions:

- **Create draft.** A planner requires the identifier to be absent and publishes
  one draft document. Ambiguous retry reuses the identifier; different existing
  content is a collision.
- **Revise draft.** A planner requires the expected draft revision and publishes
  an incremented revision. After conflict, intent must be reapplied to the
  current draft.
- **Approve.** An operator requires the exact previewed draft and readable
  policy. The commit publishes the approved authority envelope. Changed work or
  policy stops the operation.
- **Claim.** A worker requires approved work whose readiness and capability
  gates pass. The commit publishes active work and its claim. If
  `attempt_receipt_id` identifies a verified transferable handoff, the new claim
  adopts that exact candidate. A losing claim stops.
- **Register or update candidate.** The claiming worker requires its exact
  active claim and unconsumed checkpoint and publishes the exact candidate while
  advancing the checkpoint. Retry is valid only for the same candidate
  transition.
- **Authorize external mutation.** The claiming worker requires its exact active
  claim and unconsumed checkpoint. The commit advances the checkpoint only after
  current revision, policy, ticket, candidate, and authority pass. The returned
  allowance applies to one named action.
- **Block.** The claiming worker requires its exact active claim and atomically
  publishes blocked work, its blocking message, and an attempt receipt
  referenced by `attempt_receipt_id`. Retry is valid only while that same claim
  remains active.
- **Resolve.** A planner or operator requires the exact unresolved current
  blocker and atomically publishes the resolution and active state. A changed
  blocker stops the operation.
- **Release.** The claiming worker or takeover actor requires a current claim on
  active, blocked, or delivered work. It publishes a receipt when attempt or
  candidate state exists, sets `attempt_receipt_id` to that exact receipt, and
  returns the work to approved with no claim. A changed claim stops the
  operation.
- **Take over.** An operator or planner requires the exact replaced claim on
  active, blocked, or delivered work. It publishes a new claim and rationale,
  copying the replaced claim's verified candidate. If no transferable candidate
  exists, it retains `attempt_receipt_id` as the explicit no-handoff record. A
  changed claim stops the operation.
- **Deliver.** The claiming worker requires current claim, candidate, policy,
  ticket, and evidence. It atomically publishes the receipt and delivered state.
  Every identity must remain current on retry.
- **Request rework.** An authorized operator requires the current delivery and
  claim. It publishes active work with the same claim and a decision message. A
  changed delivery or claim stops the operation.
- **Accept.** An authorized operator requires every approved live-evidence
  predicate to be satisfied. It publishes acceptance and accepted work. A
  changed candidate, policy, ticket, or evidence stops the operation.
- **Defer or cancel.** A planner requires draft or approved work with no claim
  and publishes the selected state. Conflict requires full reevaluation.
- **Replace or split.** A planner and operator require draft or approved work
  whose prior candidate disposition is recorded. One commit cancels the old work
  and publishes replacement drafts whose `replaces` fields name the old work.
  The inverse relationship is derived. Replacement work requires separate
  approval.

The actor named above is a protocol role. Project policy determines which actor
may perform it, except acceptance, which is operator-only in v1. Each
operation's durable result is one Git commit even when several documents change.

## Native links

Native tickets, pull requests, documents, and deployments are stored as typed
links.

Links should record:

- relation,
- provider or system,
- stable external identifier,
- URL when useful,
- optional provider-native revision or version,
- and observation timestamp when the linked state is time-sensitive.

Atelier does not copy mutable native ticket status, title, body, comments, or
review state into the mailbox as synchronized fields. Workers and audits read
live state when project policy depends on it.

The worker rechecks native-ticket identity, eligibility, and the approved
material-field digest before claim, every consequential repository or
pull-request mutation, and delivery. The operator repeats that check before
acceptance. If the ticket was materially edited, closed, or rejected outside
Atelier, the [Atelier Project Policy Contract] determines whether the approved
contract remains eligible. An invalidating conflict stops execution and produces
a blocked attempt receipt and work-threaded decision message. Neither record
silently overwrites the other.

Truth ownership remains non-synchronizing:

- Atelier owns approved intent, non-goals, authority, assignment, and acceptance
  policy;
- the native tracker owns externally governed delivery state and dependencies;
- the project repository owns code and project policy;
- and the pull-request system owns candidate, CI, review, and merge state.

Any material contradiction is reported and blocks the dependent transition.

## Derived views and audit outcomes

A fresh clone derives operational views directly from validated documents:

- ready work is approved work whose derived gates pass;
- active work is `active` or `blocked` work with a valid claim;
- decision-needed work has an unresolved `needs-decision` message;
- blocked work additionally references its one current blocking message;
- delivered work is `delivered` and references a valid delivered receipt;
- and accepted work contains an acceptance record bound to that receipt and
  candidate.

Live audit evaluates each required promise as `satisfied`, `violated`,
`unknown`, `stale`, `needs-decision`, or `authority-unreconstructable`.
Historical acceptance is never rewritten when evidence changes. The current
audit verdict cites both the acceptance commit and the live fact that changes
its present interpretation.

## Write protocol

The canonical remote must:

- permit the authorized actor to fetch and directly update the canonical branch,
- accept atomic fast-forward ref updates,
- expose the resulting commit for read-back,
- reject force pushes and branch deletion where the host supports those rules,
- and retain reachable history.

A repository that permits updates only through pull requests is not a compatible
mailbox remote. Mailbox commits are the coordination primitive; they are not
software changes awaiting code review.

Every shared mutation follows the same protocol:

1. Fetch the canonical remote branch.
1. Verify the operation's preconditions against the fetched commit.
1. Apply one logical transition in an isolated local checkout.
1. Create one commit that contains every document change required by the
   transition.
1. Push as a fast-forward update without force.
1. If rejected, fetch current state and reevaluate the operation.
1. Retry only when the operation remains valid and idempotent.
1. Read the remote branch back and verify the expected commit is reachable and
   contains the exact expected durable content.

A transition that updates several mailbox documents must update them in one
commit. Consumers never treat an unpushed commit as shared state.

Each create operation uses a stable identifier generated before the first push.
An ambiguous retry reuses that identifier so it cannot create a duplicate
message, receipt, initiative, or work item.

Retries are bounded. Conflict, uncertainty, or a changed precondition is
reported rather than hidden.

Operation-specific retry rules override a generic retry:

- a losing claim never retries;
- any independent append-only message may be replayed on a new head when its
  exact content, references, and meaning remain unchanged;
- a resolution retries only while its target remains the unresolved current
  blocker;
- approval retries only while the exact previewed revision and policy remain
  unchanged;
- candidate registration retries only for the identical candidate;
- and a receipt or acceptance retries only while claim, candidate, policy,
  native ticket, and evidence remain current.

## Failure semantics

### Remote unavailable

Participants may read previously fetched state with an explicit staleness
warning or continue private draft work.

They may not report a shared approval, claim, release, decision, delivery, or
acceptance until the remote accepts and exposes the transition.

### Push result unknown

The writer fetches the remote branch and verifies both:

1. the expected commit is reachable from the current remote head, even if later
   mailbox commits have advanced it; and
1. the expected commit's tree contains the exact document content the operation
   intended to publish.

- If both are true, the operation succeeded historically. The caller must still
  revalidate current state before any dependent action.
- If absent, the operation may be retried after fresh precondition evaluation.
- If verification is impossible, the outcome remains unknown and the writer
  stops.

### Non-fast-forward rejection

The writer fetches current state and reevaluates the semantic precondition.

It must not mechanically force, merge, or rebase a transition whose meaning may
have changed. A losing claim attempt, superseded approval, or resolved question
ends rather than retries.

### Malformed or unsupported document

Consumers fail closed for any operation that depends on the document. They
identify the path, schema, and validation problem without rewriting it
automatically.

## Schema evolution

Every structured document declares a schema name and version. V1 schemas reject
all unknown fields.

A consumer must reject an unsupported version when interpreting approval, claim,
dependency, policy, delivery, or acceptance state.

There is no general migration framework. If a future schema requires replacement
documents, the change is performed as an explicit, reviewable Git commit with
its own verification.

## No projections or server

The canonical implementation reads repository paths and documents directly.

It may build transient in-memory views during one invocation. Those views are
discarded afterward and never become shared or authoritative.

The initial design explicitly excludes:

- SQLite or another persistent index,
- generated current-state manifests,
- a background indexer,
- a webhook receiver,
- an Atelier API service,
- a synchronization daemon,
- and alternative storage backends.

If direct reads become inconvenient, the first remedies are narrower path
conventions, smaller active documents, and explicit archival organization.
SQLite is not a planned scaling stage, and a server implementation is not a
supported future backend. Atelier is allowed to stop scaling before it is
allowed to add either.

## Security and privacy

The mailbox must not contain:

- credentials,
- provider tokens,
- secrets copied from managed projects,
- private artifacts that belong in their source system,
- or information that violates the realm's trust boundary.

Repository access controls determine who may read or write mailbox content.
Branch protection and backups reduce accidental history loss but do not make Git
a tamper-proof ledger.

Document author fields, timestamps, commit authorship, and host labels are
attribution metadata, not cryptographic proof of identity. Authorization derives
from repository access, approved project policy, the work's durable authority
ceiling, and native enforcement. The initial trust-realm model does not attempt
non-repudiation among authorized writers.

## Contract tests

The first implementation should prove:

1. Concurrent claim attempts produce exactly one winner.
1. Concurrent append-only messages are both preserved exactly once.
1. A timeout-after-success is verified after later commits advance the branch.
1. An unavailable remote never produces a reported claim.
1. A blocked attempt survives the worker session and is visible to a fresh
   planner.
1. Takeover fences the prior claimant at its next mandatory checkpoint.
1. Release or takeover preserves a remotely reachable candidate handoff.
1. A local-only candidate SHA is rejected.
1. A substantive revision beneath an active claim is rejected.
1. Policy tightening blocks newly forbidden actions, while loosening never
   widens an approved authority ceiling.
1. Material native-ticket drift blocks the next consequential mutation.
1. Pull-request head drift invalidates candidate evidence and acceptance.
1. An unsupported or malformed schema fails closed.
1. A fresh clone reconstructs ready, active, blocked, delivered, and accepted
   state without a local cache.
1. No authoritative transition reports success until exact remote read-back
   verifies its commit and durable content.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier as a skill]: ./atelier-skill-design.md
[atelier project policy contract]: ./project-policy-contract.md
