# Atelier Skill Implementation Plan

## Purpose

This plan turns the [Atelier as a Skill] design into a sequence of reviewable
decisions and vertical slices. It does not preserve the current CLI as an
implementation foundation.

The plan optimizes for one question:

> Can Atelier make agentic software development faster without allowing
> implementation activity to outrun durable intent, bounded authority, current
> evidence, and human acceptance?

Codex is the v0 reference host. Atelier is the first live dogfood project.
Neither choice is evidence of generality; external validation remains a separate
gate.

## Governing constraints

- Atelier remains its own repository and installable plugin.
- Compris remains an independently installed platform dependency.
- The Git mailbox is the only shared Atelier state.
- There is no database, daemon, server, background lease, or persistent
  projection.
- Native tickets describe project work. The mailbox carries Atelier planning,
  approval, claim, coordination, receipt, and acceptance state.
- Compris owns ticket implementation and its transitive workflow. Atelier
  supplies policy, authority fences, and terminal validation; it does not copy
  or re-orchestrate that workflow.
- The v0 delivery outcome is one ready pull request. Merge, deployment, native
  ticket mutation, stack carving, and branch deletion remain outside Atelier
  authority.
- Operator acceptance is distinct from delivery, merge, push, or native-ticket
  completion.
- Backward compatibility, data migration, and dual operation are not goals.

## Phase 0: Freeze the contracts

### Work

1. Land the coordinator-neutral delegated-execution capability in Compris.
1. Record Codex as the v0 reference host and define the portable host-adapter
   boundary.
1. Reconcile the design with the 16-scenario [Mailbox Protocol Validation].
1. Approve this implementation sequence and its reset gate.

### Exit criteria

- Compris publishes and validates
    `compris.implement-ticket/delegated-execution/v2`.
- The design, [Git Mailbox Contract], [Atelier Project Policy Contract], and
  implementation plan agree on lifecycle, authority, delivery, and acceptance.
- No legacy ticket, tag, or implementation has been mutated as part of this
  phase.

## Phase 1: Prove host-native composition

Build a disposable Atelier Codex plugin with the smallest possible `work`
vertical slice. It is a composition experiment, not the new production
implementation.

### Required proof

The experiment must:

1. install Compris independently from its published repository state;
1. discover the delegated `implement-ticket` capability by its manifest;
1. validate the manifest and a structured invocation with Compris' own
   validator;
1. let a fresh Codex worker task invoke the installed skill by stable name;
1. exercise an allowed pre-mutation checkpoint;
1. exercise a denied pre-mutation checkpoint and prove that the proposed action
   did not occur;
1. exercise exact candidate-publication acknowledgement;
1. validate a terminal result against the invocation and durable checkpoint
   tail; and
1. demonstrate by inspection that the experiment contains no copied
   `implement-ticket`, review, changeset, or pull-request workflow.

Fixtures may replace live GitHub mutation in this phase, but the process must
use real Codex skill discovery and a separately installed Compris skill. A
Python-only simulation does not satisfy the proof.

### Evaluation

Run forward evaluations in fresh tasks that receive only the installed plugin,
the disposable repository, and the invocation artifacts they would have in
normal operation. Include at least:

- a successful delegated handoff;
- authority denial;
- stale sequence or continuation token;
- malformed or incompatible capability;
- candidate acknowledgement mismatch; and
- a terminal result that exceeds granted authority.

### Exit criteria

- Every required proof is reproducible from a documented command.
- Raw inputs, outputs, checkpoint ledger, and result validation are inspectable.
- An independent adversarial review finds no material composition, authority,
  durability, or evaluation-validity gap.
- Any material finding is fixed and the exact revised experiment is reviewed
  again.

## Reset gate

After Phase 1, stop and present the operator with:

- the merged Compris prerequisite and exact version;
- composition and forward-evaluation evidence;
- adversarial-review findings and dispositions;
- the proposed new implementation issue graph;
- a mapping from every open legacy issue to `superseded`, `cancelled`, retained
  doctrine, or newly represented work;
- the exact commit proposed for the annotated `atelier-cli-v2-final` tag; and
- the deletion boundary for the legacy implementation.

Do not close issues, create or push the archival tag, or remove legacy code
until the operator explicitly confirms this reset after reviewing that evidence.

## Phase 2: Cross the reset boundary

### Work

1. Revalidate that the proposed archival commit is the intended final legacy
   state.
1. Create and push the annotated `atelier-cli-v2-final` tag.
1. Close obsolete legacy issues with explicit `superseded` or `cancelled`
   rationales and links to replacement work where applicable.
1. Remove the legacy CLI, Beads and Dolt integration, worker runtime, session
   orchestration, projections, legacy configuration, and implementation-specific
   tests.
1. Preserve only doctrine, contracts, experiment evidence, repository packaging,
   and clearly reusable fixtures whose meaning survives the reset.
1. Establish the minimal plugin and skill skeleton with failing contract tests
   for the first vertical slice.

### Exit criteria

- The archival tag is remotely reachable and annotated.
- No open issue falsely describes abandoned architecture as active work.
- The default branch contains one architecture, not a compatibility bridge.
- The repository has a small, honest failing-test boundary for the new product.

## Phase 3: Build one accountable vertical slice

Implement only the path:

```text
approved work
  -> eligible work
  -> claimed work
  -> delegated implementation
  -> delivered ready PR
  -> operator acceptance
```

### Changesets

Each changeset must be independently reviewable and leave the repository in a
coherent state:

1. **Plugin and host adapter** — Codex discovery, `/atelier` entry skill, strict
   startup capability check, and exact installation failure.
1. **Mailbox documents and validation** — root, project, initiative, work,
   message, receipt, and policy schemas with fresh-clone reconstruction.
1. **Canonical Git writes** — fast-forward-only read-modify-verify writes,
   semantic retry, ambiguous-result recovery, and no persistent projection.
1. **Plan mode** — draft, revise, approve, and promote one assignment tied to
   one native GitHub ticket.
1. **Claim and checkpoint ledger** — project-serial eligibility, fenced claim,
   sequence and token transitions, takeover, and append-only authorization
   evidence.
1. **Work delegation** — construct the versioned invocation, call the separately
   installed Compris skill, validate checkpoints and terminal results, and
   record blocked or delivered receipts.
1. **Audit and acceptance** — reread native state, evaluate the finite evidence
   predicates, report uncertainty, and record explicit operator acceptance.

Do not add additional providers, parallel project work, automatic merge,
deployment, a dashboard, SQLite, a server, or migration support during this
phase.

### Exit criteria

- A fresh planner task and a fresh worker task coordinate only through native
  project state and a fresh clone of the mailbox.
- A worker can disappear after every consequential boundary without losing the
  durable explanation of what happened.
- No action exceeds the intersection of approved policy, current policy,
  approved work, invocation authority, and host enforcement.
- Delivery and acceptance fail closed when current evidence is missing, stale,
  violated, or unknown.
- The complete Atelier dogfood changeset is human-shaped and reviewable.

## Phase 4: Dogfood on Atelier

Use the new skill to plan and deliver the remaining Atelier v0 implementation
work. Keep merge authority and acceptance with the operator.

Measure:

- operator time required to understand and approve assignments;
- number and cause of blocked or restarted worker attempts;
- recovery quality after deliberate task interruption;
- review findings caused by scope or contract ambiguity;
- stale-evidence detection;
- changeset size and conceptual coherence; and
- whether the mailbox makes the current accountability state easier to explain
  than the native ticket and pull request alone.

Dogfooding succeeds only if the records materially improve supervision and
handoff. Completing code faster is insufficient.

## Phase 5: Test the product claim

Run one cross-project Tuber and Peeler initiative, then one constrained
environment where Atelier cannot mutate the native tracker.

The cross-project evaluation must prove that:

- one initiative can promote project-specific assignments without pretending the
  repositories share a native epic;
- each worker sees only its own approved assignment and project policy;
- cross-project blockers and decisions survive task boundaries in the mailbox;
- each repository produces its own reviewable candidate and evidence; and
- acceptance can proceed independently without obscuring initiative-level
  obligations.

The constrained evaluation must prove useful planner-worker communication
without native-ticket writes. If either evaluation requires a server,
projection, or copied Compris workflow, stop and revisit the product
boundary rather than expanding the architecture.

## Decision points after v0

Only validated demand may justify:

- a Claude Code host adapter;
- another native ticket provider;
- multiple active assignments in one project;
- `ready_prs`, merge, or deployment outcomes;
- richer derived views rebuilt from Git on demand; or
- additional Compris capability contracts.

None of these decisions justify a server-backed mailbox. If Git alone becomes
insufficient, treat that as evidence that the product shape should change, not
as an automatic reason to add a database or daemon.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier as a skill]: atelier-skill-design.md
[atelier project policy contract]: project-policy-contract.md
[git mailbox contract]: git-mailbox-contract.md
[mailbox protocol validation]: mailbox-protocol-validation.md
