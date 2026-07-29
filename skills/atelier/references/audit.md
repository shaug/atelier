# Audit and acceptance

Use this boundary only for one validated mailbox assignment whose current state
is `delivered` or `accepted`.

## Live audit

1. Complete the host preflight in `host-boundary.md`.
2. Read the canonical mailbox through `GitMailboxWriter.observe`; do not reuse a
   prior clone or write an audit projection.
3. Generate one complete `atelier.github-observation/v1` snapshot at the live
   read boundary. It must include the exact issue relationships, pull request,
   comments, reviews, checks, effective required-check configuration, and review
   threads. A failed ruleset or branch-protection read is represented by
   `required_checks.configuration_read: false`; it is never inferred from the
   visible check list.
4. Normalize the exact aggregate `review-code-change` result and every deliberate
   disposition for a nonempty top-level review or pull-request comment into an
   `atelier.audit-evidence/v1` JSON object. Each review finding records an ID,
   summary, disposition, rationale, and optional follow-up. Each live review or
   comment disposition records its kind, provider ID, exact `sha256:` body digest,
   disposition, rationale, and optional follow-up. Omitted, duplicate, foreign,
   or body-stale identities fail closed.
5. Invoke `scripts/audit.py audit` with the mailbox remote and branch, work ID,
   policy target, host target, observation path and lower bound, and
   `--audit-evidence` path.
6. Present the complete report. Every registry predicate is classified as
   `satisfied`, `violated`, `unknown`, or `stale`; the report also preserves the
   structured review findings, receipt obligations, and explicit disposition and
   body of every review, pull-request comment, and thread.

The report reconstructs the exact delivered receipt, remote candidate, pull
request, head and comparison base, approved and current policy, native ticket
observation, required validation, independent `review-code-change` result, and
current feedback. An accepted assignment additionally derives the Git commit
that introduced acceptance and the preceding delivery observation. Later drift
changes the current audit verdict; it never rewrites historical acceptance.

Audit is read-only. Missing host capability or project-policy identity reports
`authority-unreconstructable`. Missing live evidence reports `unknown`.
Contradictory state reports `violated`; changed candidate-bound state reports
`stale`.

## Explicit acceptance

Acceptance is a second operation. Do not infer it from a clean audit.

1. Show the operator the report and its `acceptance_fence`.
2. Require explicit confirmation of that exact fence.
3. Start a new provider read only after the confirmed report's `observed_at`.
   Produce a second complete observation whose live-read lower bound and
   `observed_at` are both strictly later. Reusing the report snapshot is rejected.
4. Invoke `scripts/audit.py accept` with that second observation and lower bound,
   the same normalized audit-evidence path, the complete fence, `--accepted-at`,
   and `--confirm`.
5. The transition rereads the canonical mailbox, host boundary, policy, ticket,
   candidate, pull request base and head, required-check configuration and
   results, reviews, comments, and threads. It requires the fence's mailbox,
   receipt, candidate, and semantic evidence digest to remain exact while the
   observation timestamp advances. Changed facts are rejected as stale or
   violated; only the observation timestamp may differ.
6. Only when every currently required predicate and the unconditional
   no-unresolved-feedback guard are `satisfied` does one verified mailbox commit
   move `delivered` to `accepted`, clear the claim, and bind the operator record
   to the exact receipt, candidate, audit evidence, and satisfied verdicts. The
   accepted timestamp is always checked against the current UTC clock, even when
   no test clock is supplied.

Acceptance does not merge a pull request, deploy, mutate or close a native
ticket, delete a branch, or accept a parent initiative.
