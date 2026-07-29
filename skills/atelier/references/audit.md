# Audit and acceptance

Use this boundary only for one validated mailbox assignment whose current state
is `delivered` or `accepted`.

## Live audit

1. Complete the host preflight in `host-boundary.md`.
2. Read the canonical mailbox through `GitMailboxWriter.observe`; do not reuse a
   prior clone or write an audit projection.
3. Generate one complete `atelier.github-observation/v1` snapshot at the live
   read boundary. It must include the exact issue relationships, pull request,
   comments, reviews, checks, and review threads.
4. Invoke `scripts/audit.py audit` with the mailbox remote and branch, work ID,
   policy target, host target, observation path, and observation lower bound.
5. Present the complete report. Every registry predicate is classified as
   `satisfied`, `violated`, `unknown`, or `stale`; the report also preserves
   receipt obligations and the visible disposition and body of every review,
   pull-request comment, and thread.

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
3. Invoke `scripts/audit.py accept` with the same fresh-read inputs, the complete
   fence, `--accepted-at`, and `--confirm`.
4. The transition rereads the canonical mailbox, host boundary, policy, ticket,
   candidate, pull request, checks, reviews, comments, and threads. It rejects
   any changed report digest, mailbox revision, receipt, candidate, policy,
   ticket, or evidence.
5. Only when every currently required predicate is `satisfied` does one verified
   mailbox commit move `delivered` to `accepted`, clear the claim, and bind the
   operator record to the exact receipt and candidate.

Acceptance does not merge a pull request, deploy, mutate or close a native
ticket, delete a branch, or accept a parent initiative.
