# Claim and checkpoint boundary

Use `../scripts/claiming.py` for the production portion of work mode owned by
shaug/atelier#778. It is the only supported path for claim acquisition,
delegated-execution checkpoint authorization, candidate acknowledgement, block,
release, and takeover.

This boundary does not launch `implement-ticket`, validate a terminal delegated
result, deliver work, audit a pull request, or record operator acceptance. Those
remain unavailable until #779 and #780 implement them.

## Preconditions

Before `claim`, `checkpoint`, or `takeover`:

1. Complete the fail-closed host preflight in `host-boundary.md`.
2. Supply one complete GitHub observation captured at or after the operation's
   `not_before` boundary.
3. Supply the managed project's current policy checkout, remote, full canonical
   ref, and `.atelier/policy.yaml` path.
4. Supply the exact canonical mailbox commit that first contains the approved
   work revision.
5. Supply the exact installed Agent Scripts skill root, stable name, connector
   identity, and complete read-only operation set required by the host descriptor.

The script binds the policy remote's canonical GitHub URL to the managed project
repository identity, rechecks the pinned host capability, and rereads approved and
current policy, the canonical mailbox, the approved work transition, and the
material ticket observation during every write attempt. It combines policy using
the Project Policy Contract and fails closed on incompatible identity, eligibility,
authority, capability, or evidence drift.

## Commands

Generate durable identifiers before the first attempt so retries reuse them:

```text
python3 skills/atelier/scripts/claiming.py new-id clm
python3 skills/atelier/scripts/claiming.py new-id run
python3 skills/atelier/scripts/claiming.py new-id msg
python3 skills/atelier/scripts/claiming.py new-id rcp
```

Run one transition with a JSON request:

```text
python3 skills/atelier/scripts/claiming.py claim request.json
python3 skills/atelier/scripts/claiming.py checkpoint request.json
python3 skills/atelier/scripts/claiming.py block request.json
python3 skills/atelier/scripts/claiming.py release request.json
python3 skills/atelier/scripts/claiming.py takeover request.json
```

Every request contains:

```json
{
  "mailbox": {
    "remote": "git@github.com:example/atelier-mailbox.git",
    "canonical_branch": "main",
    "max_attempts": 3
  },
  "work_id": "wrk_019f9a9e-0000-7000-8000-000000000001"
}
```

Execution-state operations additionally contain:

```json
{
  "approved_commit": "0123456789abcdef0123456789abcdef01234567",
  "host": {
    "descriptor_path": "/absolute/path/to/atelier/references/host-capability.json",
    "skill_name": "agent-scripts:implement-ticket",
    "skill_root": "/absolute/path/to/installed/implement-ticket",
    "connector": "github@openai-curated",
    "operations": ["read_issue", "read_issue_relationships"]
  },
  "observation": {
    "path": "/absolute/path/to/github-observation.json",
    "not_before": "2026-07-28T12:00:00Z"
  },
  "policy": {
    "checkout": "/absolute/path/to/managed-project",
    "remote": "origin",
    "canonical_ref": "refs/heads/main",
    "path": ".atelier/policy.yaml"
  },
  "now": "2026-07-28T12:00:30Z"
}
```

`now` is optional and exists for deterministic hosts and contract tests.

## Claim

Add `claim_id`, `worker_run_id`, `continuation_token`, and `claimed_at`. A claim
is allowed only for approved work whose dependencies, project-serial gate,
policy, native ticket, and capability gate pass. A released transferable
candidate is adopted only after its exact remote ref and head are verified.

Two claimers may plan concurrently, but only the verified canonical
fast-forward winner owns the assignment. A losing claimant stops.

## Checkpoint

Add a `checkpoint` object containing:

- the current `fence` (`claim_id`, `worker_run_id`, `sequence`, and
  `continuation_token`);
- `phase`, `action`, and `proposed_effect_digest`;
- `candidate_head` and `acknowledged_candidate_head`, including explicit nulls;
- a new `next_continuation_token`;
- `recorded_at`; and
- `candidate`, explicitly null except for `candidate_published`.

Each allowed transition increments the sequence by one, rotates the token, and
appends one authorization. Denial does not advance the ledger. A
`candidate_published` checkpoint must immediately follow the exact candidate
push authorization and verifies the declared remote ref and head before
recording the candidate.

## Block, release, and takeover

`block` and `release` require the complete current `fence`.

- `block` adds stable `message_id` and `receipt_id` values, a subject, detail,
  timestamp, and optional validation/review evidence. It retains the claim and
  mutation ownership.
- `release` adds a stable `receipt_id`, reason, timestamp, and optional evidence.
  It relinquishes mutation ownership, clears the claim, and preserves an exact
  transferable candidate when one exists. A blocked release retains the unanswered
  decision message as historical audit evidence without treating it as a current
  blocker or falsely resolving it. Historical blockers are derived from released
  execution identities and explicit takeover handoffs, never global wall-clock order.
- `takeover` requires the exact `replaced_fence`, fresh claim and run
  identifiers, a fresh continuation token, a stable `takeover_message_id`, a
  reason, and timestamp. It records the rationale, starts an empty checkpoint
  ledger, and copies the prior candidate exactly. Blocked takeover preserves the
  unresolved blocker and remains blocked. Delivered takeover clears only the
  delivery pointer, retains the delivery as the current historical attempt, and
  returns the transferred candidate to active work.

Never invent a token after losing it, reuse a released claim or run identity,
discard a candidate during takeover, combine release and reacquisition into one
transition, or treat a local-only candidate as transferable.
