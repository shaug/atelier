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
- The worker claims it and delegates its implementation to Compris.
- A fresh recovery task reconstructs state after a deliberate interruption.
- The auditor reads the delivered state and presents predicate verdicts.
- The operator alone may accept the audited delivery.

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
2. Read `claiming.md`. From canonical mailbox Git history, identify the exact
   commit that promoted the current work revision to `approved`; supply it as
   `approved_commit` when claiming the eligible assignment with
   `scripts/claiming.py claim`. Retain the returned claim ID, worker run ID,
   continuation token, canonical claim-transition `commit`, and `base_revision`.
3. Read `delegation.md`. Use `scripts/delegation.py` with `operation: prepare`
   to write one immutable Compris v2 invocation to the current task's
   host-local path. Preparation seals only the invocation digest into the claim;
   the invocation and its host-owned fresh observation command are not shared
   mailbox state and are not reusable by a recovery task.
4. Give that unchanged invocation to one fresh
   `compris:implement-ticket` worker. The implementation worker follows
   Compris' own workflow, uses every checkpoint before an allowed
   external mutation, and sends `candidate_published` immediately after every
   remote candidate advancement.
5. Finalize only the returned terminal result with a fresh GitHub observation.
   A `ready_pr` receipt must name one open, non-draft, mergeable ordinary pull
   request and its exact remote ref and head. A blocked result must preserve its
   exact acknowledged candidate, if one exists, and its remaining obligation.
   Finalize `requires_epic` as the production blocked, planner-action receipt;
   preserve any transferable candidate and return the assignment to planning.
   Do not invoke `implement-epic` from this runbook.

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
2. reconstruct the work lifecycle, claim fence, checkpoint ledger, receipts, and
   any exact remote candidate using `mailbox-validation.md`;
3. verify a declared candidate against its full remote ref and head before
   treating it as transferable; and
4. choose the production transition from the reconstructed lifecycle:
   - for active work whose worker is being replaced, use `takeover` with the exact
     replaced fence;
   - for blocked work whose worker is being replaced, use `takeover` and preserve
     the unresolved blocker and blocked state. Takeover does not resolve the
     decision or make the replacement claim active. Present the blocker for an
     explicit planner or operator decision; when that decision authorizes another
     attempt, use `release` with the replacement claim's exact blocked fence to
     return the work to approved while preserving its receipt and transferable
     candidate. Start a separate fresh `claim` with new claim, run, and token
     identities before preparing another invocation;
   - for released, approved work, use a fresh `claim`; verify and inherit any exact
     transferable candidate, and do not combine release with reacquisition; or
   - for delivered work, leave the delivery intact for the separate audit task.
     Use delivered `takeover` only after an independently authorized rework decision
     because it returns the transferred candidate to active work.

When an active `takeover` or a fresh `claim` produces a new active claim, repeat the
preconditions in `delegation.md` against that new fence: capture a fresh complete
GitHub observation, use `scripts/delegation.py` `prepare` to seal a new immutable
invocation into the claim, pass it unchanged to one fresh
`compris:implement-ticket` worker, service every checkpoint, and finalize the
terminal result with another fresh observation. Never reuse the prior claim's
invocation after takeover or a fresh claim, even when the native ticket is unchanged.
A recovery that remains blocked is truthful blocked evidence, not a delivered or
completed end-to-end dogfood run.

The recovery task must retain the prior fence and token as historical evidence.
It must never mint a token, guess a candidate SHA, reuse a stale observation,
or continue an invocation whose material ticket observation has changed.

## Audit, then obtain an operator decision

After a delivered `ready_pr` receipt, start a separate audit task. Read
`audit.md`, complete the host preflight, reconstruct the mailbox from its
canonical branch, and capture one complete current GitHub observation. Run a
fresh `review-code-change` in that audit task against the receipt-bound delivered
head and comparison base, using raw current evidence rather than a worker-local
artifact. Normalize that exact aggregate result and every live review/comment
disposition, then run `scripts/audit.py audit`. The delivery receipt contributes
only the review identity and verdict; the normalized audit-evidence file remains
a temporary host output unless explicit acceptance persists it.

Present the complete report and its acceptance fence to the operator. Every
predicate must remain visibly `satisfied`, `violated`, `unknown`, or `stale`;
do not summarize a missing predicate as clean.

Only an explicit confirmation of that exact fence may begin acceptance. Capture
a strictly newer complete observation, then run `scripts/audit.py accept` with
the same evidence and the confirmed fence. Acceptance records the operator's
decision in the mailbox. It does not merge, deploy, mutate or close the native
ticket, delete a branch, or accept the parent initiative.

If the operator declines the fence, do not run `accept` and do not invent a
rejection record. The current v0 production boundary has no durable rejection
transition: the work remains delivered, and a separate authorized product
change is required before this runbook can claim to preserve a rejected
decision.

## Preserve the evidence packet

Use only native GitHub state and canonical-mailbox records for cross-task
reconstruction:

| Transition | Durable production record |
| --- | --- |
| Approval | Work ID and approved revision, approver/timestamp, policy commit, authority ceiling, and required evidence. |
| Claim and delegation | Claim ID, worker run ID, full checkpoint ledger, immutable invocation digest, and exact Compris capability identity. |
| Candidate and delivery | Remote URL, full ref, head SHA, candidate acknowledgement, required validation results, independent review identity/verdict, and pull-request topology. |
| Recovery | Previous fence, checkpoint tail, block/release/takeover receipt, rationale, and verified transferable candidate or explicit absence. |
| Audit and acceptance | Persisted predicate verdicts, normalized review and feedback evidence, and the acceptance commit when explicitly accepted. A declined fence remains delivered; v0 records no rejection transition. |

The rendered preview and digest, complete provider-observation files, and audit
report and fence are temporary operator or host outputs. Use them only at their
live decision boundaries; production v0 does not persist them as shared Atelier
state. A fresh task captures a new provider observation and reconstructs the
durable records above instead of expecting those files to survive.

If a dogfood acceptance criterion requires retaining one of those raw temporary
artifacts, report the run blocked: v0 has no authorized durable production path
for it. Do not invent another mailbox document, commit host-local output, or
replace the missing artifact with a narrative claim that the run passed. Also
report any durable item that cannot be reread, is stale, or conflicts with
current native or mailbox state.
