# Mailbox Protocol Validation

## Status

The disposable v0 protocol experiment passed all 15 acceptance scenarios on
2026-07-25.

The experiment is implemented in `experiments/mailbox_protocol_v0.py` and runs
entirely against temporary local bare Git repositories and independent clones.
It removes those repositories after each run.

## Command

```text
python3 experiments/mailbox_protocol_v0.py
```

## Results

1. Concurrent claim attempts produced exactly one winner.
1. Concurrent append-only messages survived exactly once after semantic retry.
1. A simulated lost push response remained verifiable by ancestry and exact
   historical content after a later commit.
1. A claim push to an unavailable remote failed and left no shared claim.
1. A blocker survived the worker session and was visible to a fresh planner.
1. After takeover, the prior claimant's next sequence-and-token checkpoint was
   denied.
1. Fresh mailbox and project clones discovered the current release receipt from
   `work.md`, recovered its remotely reachable candidate, and verified that a
   later takeover preserved that candidate.
1. A local-only candidate SHA was rejected.
1. A substantive revision beneath an active claim was rejected.
1. Policy tightening removed authority and later loosening did not widen the
   approved ceiling.
1. Material native-ticket drift invalidated the current invocation.
1. Pull-request head drift invalidated delivery evidence and acceptance.
1. An unsupported schema failed closed.
1. A fresh clone reconstructed approved, active, blocked, delivered, and
   accepted work plus each referenced blocker, receipt, and acceptance binding.
1. A fresh clone derived ready work only when dependency, project policy,
   native-ticket, capability, and project-serial-execution gates all passed.
1. Every reported authoritative transition had an exact remote read-back.

## What this validates

The experiment validates the proposed Git concurrency and durability model:

- fast-forward-only canonical writes;
- losing-claim behavior;
- semantic retry of independent append-only documents;
- timeout recovery through ancestry and exact-content verification;
- durable blockers, claims, authorization records, receipts, and candidate
  handoffs;
- cooperative takeover fencing through an actual stale checkpoint attempt;
- lifecycle reconstruction, including referenced artifacts, from a fresh clone;
  and
- the absence of a database, daemon, lease server, or persistent projection.

Frontmatter uses JSON object syntax, which is a strict valid subset of YAML.
This keeps the experiment dependency-free while exercising Markdown documents
with structured YAML frontmatter.

## What this does not validate

This is a protocol experiment, not an Atelier implementation. It does not prove:

- compatibility with every Git hosting service;
- real GitHub ticket, pull-request, review, or check API behavior—the drift
  scenarios exercise only deterministic contract predicates;
- operator identity or authorization;
- host-specific skill discovery and invocation;
- network partitions beyond explicit failure and ambiguous-result cases;
- complete production schema validation; or
- usability of the planner and worker prompts.

Those boundaries remain forward-evaluation work for the first skill
implementation. The experiment is sufficient to keep the passive Git mailbox as
the proposed backing mechanism; it is not evidence that the rest of Atelier is
implemented.
