# Dogfood one accountable changeset

Use this runbook to exercise one small Atelier change from a human-approved
assignment through a ready pull request, live audit, and an explicit operator
decision. It is a procedure for collecting evidence, not evidence that any
particular dogfood run succeeded.

The disposable composition experiment is not a substitute for this run. This
run uses one real GitHub-backed Atelier assignment and the production planning,
claiming, delegation, audit, and acceptance boundaries.

## Choose the change and roles

Select one open native GitHub ticket that is independently reviewable, has no
unresolved native blocker, and can finish at one ordinary ready pull request.
Do not use this runbook to add another provider, a stack, merge, deployment,
ticket mutation, or a later evaluation.

Keep these roles in separate tasks:

- The planner discusses and promotes the assignment.
- The worker claims it and delegates its implementation to Agent Scripts.
- A fresh recovery task reconstructs state after a deliberate interruption.
- The auditor reads the delivered state and presents predicate verdicts.
- The operator alone accepts or rejects the audited delivery.

Each task may read native GitHub state and reconstruct the canonical Git
mailbox. No task may rely on another task's transcript, an uncommitted local
file, or a host-local projection as shared state.

## Plan and promote in a planner task

1. Complete the host preflight in `host-boundary.md` and capture a complete
   GitHub observation at a new read boundary.
2. Read `planning.md`. Create or revise one complete draft with
   `scripts/planning.py`; give it a single ticket, bounded scope, non-goals,
   constraints, done definition, verification expectations, and review shape.
3. Preview the exact draft revision against a fresh observation and the current
   project policy. Show the operator the rendered assignment, policy commit,
   authority ceiling, required evidence, and preview digest.
4. Wait for the operator to approve that exact preview. Capture a newer
   observation after that confirmation, then promote the same revision with
   `scripts/planning.py approve`.

The promotion is the durable implementation boundary. Drafting, previewing, or
asking to continue does not grant worker authority.

## Claim and delegate in a separate worker task

1. Start without the planner transcript. Complete a fresh host preflight, read
   the canonical mailbox with `mailbox-validation.md`, and capture a complete
   current GitHub observation.
2. Read `claiming.md`. Claim only the approved, eligible assignment with
   `scripts/claiming.py claim`; retain the returned claim ID, worker run ID,
   continuation token, and approved mailbox commit.
3. Read `delegation.md`. Use `scripts/delegation.py` with `operation: prepare`
   to seal one immutable Agent Scripts v2 invocation and its host-owned fresh
   observation command into the claim.
4. Give that unchanged invocation to one fresh
   `agent-scripts:implement-ticket` worker. The implementation worker follows
   Agent Scripts' own workflow, uses every checkpoint before an allowed
   external mutation, and sends `candidate_published` immediately after every
   remote candidate advancement.
5. Finalize only the returned terminal result with a fresh GitHub observation.
   A `ready_pr` receipt must name one open, non-draft, mergeable ordinary pull
   request and its exact remote ref and head. A blocked result must preserve its
   exact acknowledged candidate, if one exists, and its remaining obligation.

Atelier validates the invocation, checkpoint fence, candidate acknowledgement,
and terminal result. It does not implement the ticket workflow, merge the pull
request, or close the issue.

## Exercise interruption and fresh-task recovery

Deliberately stop the original worker only at a durable boundary: after its
claim, a checkpoint response, candidate acknowledgement, block, release, or
delivery receipt. Do not interrupt an in-flight mailbox write and then invent a
replacement result.

Start a new task with no earlier task transcript. It must:

1. repeat the host preflight and reread the native ticket, current policy, and
   canonical mailbox;
2. reconstruct the active work, claim fence, checkpoint ledger, receipts, and
   any exact remote candidate using `mailbox-validation.md`;
3. verify a declared candidate against its full remote ref and head before
   treating it as transferable; and
4. use the explicit `block`, `release`, or `takeover` transition in
   `claiming.md` when its preconditions pass.

The recovery task must retain the prior fence and token as historical evidence.
It must never mint a token, guess a candidate SHA, reuse a stale observation,
or continue an invocation whose material ticket observation has changed.

## Audit, then obtain an operator decision

After a delivered `ready_pr` receipt, start a separate audit task. Read
`audit.md`, complete the host preflight, reconstruct the mailbox from its
canonical branch, and capture one complete current GitHub observation. Normalize
the exact aggregate `review-code-change` result and every live review/comment
disposition, then run `scripts/audit.py audit`.

Present the complete report and its acceptance fence to the operator. Every
predicate must remain visibly `satisfied`, `violated`, `unknown`, or `stale`;
do not summarize a missing predicate as clean.

Only an explicit confirmation of that exact fence may begin acceptance. Capture
a strictly newer complete observation, then run `scripts/audit.py accept` with
the same evidence and the confirmed fence. Acceptance records the operator's
decision in the mailbox. It does not merge, deploy, mutate or close the native
ticket, delete a branch, or accept the parent initiative.

## Preserve the evidence packet

Keep the following identifiers and artifacts available through native GitHub
state or the canonical mailbox:

| Transition | Required durable evidence |
| --- | --- |
| Approval | Work ID and revision, rendered preview digest, approver/timestamp, policy commit, authority ceiling, and required evidence. |
| Claim and delegation | Claim ID, worker run ID, full checkpoint ledger, immutable invocation digest, and exact Agent Scripts capability identity. |
| Candidate and delivery | Remote URL, full ref, head SHA, candidate acknowledgement, required validation results, independent review identity/verdict, and pull-request topology. |
| Recovery | Previous fence, checkpoint tail, block/release/takeover receipt, rationale, and verified transferable candidate or explicit absence. |
| Audit and acceptance | Complete provider observations, normalized review and feedback dispositions, audit report/fence, explicit operator decision, and acceptance commit when accepted. |

If any item cannot be reread, is stale, or conflicts with current native or
mailbox state, report that condition. Do not replace it with a narrative claim
that the dogfood run passed.
