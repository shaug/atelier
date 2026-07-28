# Plan-mode boundary

Issue #777 implements only planning for one GitHub-backed assignment:

- create one non-executable draft assignment and an optional initiative;
- revise one exact draft revision;
- preview the exact assignment and referenced initiative, live ticket
  observation, current project policy, authority ceiling, and acceptance evidence;
- wait for explicit operator approval; and
- promote only that previewed revision to `approved`.

It does not claim work, choose a worker, invoke Agent Scripts, create or update a
pull request, accept delivery, mutate a native ticket, merge, deploy, or clean up.

## Required live inputs

Before any command, complete the host preflight in `host-boundary.md`. The
planner requires:

- one complete `atelier.github-observation/v1` JSON document captured at or
  after a caller-recorded live-read boundary;
- one explicitly selected mailbox remote and canonical branch;
- the stable active mailbox project identifier;
- a managed-project checkout, remote, canonical full branch ref, and project
  policy path; and
- stable `ini_...` and `wrk_...` UUIDv7 identifiers generated before the first
  create attempt.

Generate identifiers once and retain them across ambiguous retries:

```text
python3 scripts/planning.py new-id ini
python3 scripts/planning.py new-id wrk
```

The helper accepts one JSON request for each phase. Host-local paths occur only
in the invocation request; they are never written to the mailbox.

## Draft and revision

`create` requires a complete `assignment`, an optional `initiative`, and the
live observation boundary:

```json
{
  "mailbox": {
    "remote": "git@github.com:example/atelier-mailbox.git",
    "canonical_branch": "main"
  },
  "observation": {
    "path": "/host/path/github-observation.json",
    "not_before": "2026-07-28T04:00:00Z"
  },
  "initiative": {
    "id": "ini_019f9a9e-0000-7000-8000-000000000001",
    "title": "Accountable outcome",
    "intent": "Why this initiative exists.",
    "rationale": "Why the outcome matters.",
    "non_goals": "What the initiative excludes.",
    "constraints": "Durable initiative constraints.",
    "edge_cases": "Known cross-project edges.",
    "related_context": "Context later assignments need.",
    "outcome": "The initiative-level result."
  },
  "assignment": {
    "id": "wrk_019f9a9e-0000-7000-8000-000000000001",
    "title": "One reviewable change",
    "project_id": "prj_019f9a9e-0000-7000-8000-000000000001",
    "initiative_id": "ini_019f9a9e-0000-7000-8000-000000000001",
    "dependencies": [],
    "replaces": [],
    "ticket_number": 123,
    "ticket_url": "https://github.com/example/project/issues/123",
    "intent": "The exact intended behavior.",
    "rationale": "Why the project needs it.",
    "scope": "The complete bounded implementation scope.",
    "non_goals": "Named exclusions.",
    "constraints": "Architecture and authority constraints.",
    "edge_cases": "Known behavior at the boundary.",
    "related_context": "Context that survives the planner task.",
    "done_definition": "Observable completion criteria.",
    "verification_expectations": "Required validation evidence.",
    "review_shape_guidance": "How to keep the change human-shaped."
  }
}
```

Run:

```text
python3 scripts/planning.py create /host/path/create.json
```

The transition writes one `draft` work document with `approval: null` and
`claim: null`. It creates no executable authority. If `initiative` is present,
the initiative and work document are published in the same verified mailbox
commit.

`revise` uses the same shape plus `expected_revision`. It requires the work to
remain `draft`, requires the exact expected revision, and increments it once:

```text
python3 scripts/planning.py revise /host/path/revise.json
```

Never silently fill a missing worker-contract section. Ask the operator for the
missing intent, non-goal, constraint, edge case, done definition, verification
expectation, or review-shape decision before creating or revising the draft.

## Preview

Build a preview request after the draft is complete:

```json
{
  "mailbox": {
    "remote": "git@github.com:example/atelier-mailbox.git",
    "canonical_branch": "main"
  },
  "observation": {
    "path": "/host/path/fresh-github-observation.json",
    "not_before": "2026-07-28T04:05:00Z"
  },
  "work_id": "wrk_019f9a9e-0000-7000-8000-000000000001",
  "expected_revision": 2,
  "policy": {
    "checkout": "/host/path/managed-project",
    "remote": "origin",
    "canonical_ref": "refs/heads/main",
    "path": ".atelier/policy.yaml"
  },
  "envelope": {
    "authority_ceiling": [
      "repository.candidate.create",
      "repository.candidate.push",
      "pull_request.create",
      "pull_request.update"
    ],
    "required_evidence": [
      "candidate-remote-reachable",
      "pull-request-head-current",
      "pull-request-open",
      "pull-request-mergeable",
      "required-checks-pass",
      "required-validation-reported",
      "independent-review-current",
      "unresolved-feedback-zero"
    ]
  }
}
```

Run:

```text
python3 scripts/planning.py preview /host/path/preview.json
```

The preview fails closed unless:

- the exact draft revision exists;
- the project is active and repository-specific;
- the complete GitHub observation is fresh;
- the ticket link, repository, and observed identity agree;
- the ticket state is allowed and every native blocker is closed;
- no canonical pull-request observation already owns the ticket;
- the current project policy is fetched from its canonical ref;
- the project, mailbox, repository, policy path, and policy identities agree;
- requested authority is a subset of current policy; and
- proposed evidence includes everything current policy requires.

Show the operator the complete rendered initiative and assignment, revision,
ticket identity, policy commit and path, authority ceiling, acceptance evidence,
and returned `preview_digest`. Do not treat a request to draft, revise, preview,
or continue as approval.

## Explicit promotion

Pause after preview and ask the operator to approve that exact revision and
envelope. Only a new, explicit operator confirmation authorizes `approve`.

Copy the complete preview result into a separate approval request and add:

```json
{
  "approved_by": "operator",
  "approved_at": "2026-07-28T04:10:00Z"
}
```

Retain the same `mailbox`, use a newly captured `observation`, and repeat the
same `policy` target. The observation live-read boundary must be at or after the
operator confirmation timestamp; a preview-time observation cannot be reused.
Run:

```text
python3 scripts/planning.py approve /host/path/approve.json
```

Approval rereads the canonical mailbox, referenced initiative, current policy
ref, and fresh GitHub observation. Any material ticket, policy, initiative,
draft, revision, repository, authority, evidence, or preview drift rejects the
transition. An
attribution-only ticket-title change does not invalidate a policy material-field
digest. A successful transition records:

- `status: approved`;
- the exact approved work revision;
- `approved_by: operator` and the explicit approval timestamp;
- the exact current policy repository, commit, and path;
- the approved authority ceiling; and
- operator-only acceptance mode with the required evidence.

It leaves `claim`, candidate, receipt, delivery, and acceptance state empty.
Worker eligibility, claiming, checkpointing, and delegation belong to later
graph issues.
