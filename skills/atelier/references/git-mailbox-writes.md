# Canonical Git mailbox writes

Issue #776 provides the production persistence boundary for mailbox transitions.
It does not implement `plan`, `work`, `audit`, or any transition-specific
authority decision.

Import `GitMailboxWriter` from `scripts/git_mailbox.py`. A caller supplies:

- the mailbox remote and canonical branch;
- one stable operation name;
- a `revalidate(context)` callback that rereads every applicable current policy,
  native-ticket, claim, candidate, and authority precondition; and
- a `plan(context)` callback returning the complete document set for one
  semantic transition.

The writer always reconstructs and validates the fetched mailbox before either
callback runs. After contention it fetches again, discards the stale local
commit, reconstructs current state, and invokes both callbacks again. A
transition callback is read-only; it returns complete UTF-8 replacements or
deletions and cannot mutate its checkout directly. Message and receipt
documents are append-only: a plan cannot delete them or target an identifier
that already exists in the fetched mailbox. While a claim remains current, its
checkpoint authorization ledger must retain the fetched ledger as an exact
prefix, and its sequence and continuation token advance together. Release,
takeover, and a new claim remain distinct lifecycle transitions. In particular,
one plan cannot both append the current claim's release receipt and install a
different claim.

Git commands are noninteractive and have a finite timeout. A mailbox remote
must be a repository operand and cannot begin with `-`. Fetch timeouts fail as
unavailable current state. Push timeouts enter the same exact read-back and
recovery path as any other ambiguous push result.

Each successful operation:

1. starts from the fetched canonical commit in an isolated temporary checkout;
2. validates current mailbox documents and caller-owned external preconditions;
3. applies and validates one declared semantic transition;
4. creates one ordinary Git commit;
5. verifies that the commit is the single child of the fetched base and contains
   exactly the declared paths and bytes;
6. pushes that exact commit with an expected-old-ref lease equal to the fetched
   base;
7. fetches the branch again; and
8. verifies that the commit is an ancestor of the remote head and that its
   historical tree contains the exact declared content.

Retries are bounded. A non-fast-forward result is not mechanically rebased:
the operation is replanned only after fresh semantic revalidation. Callers
reject losing claims, changed approvals, resolved questions, stale checkpoints,
policy or ticket drift, and any other invalidated transition with
`MailboxTransitionRejected`. A deleted, rewound, or divergent canonical ref
cannot satisfy the lease; deletion remains unavailable, while rewind or
divergence fails closed instead of becoming a new retry base.

If a push response is lost and read-back is unavailable,
`MailboxPersistenceUnknown` exposes a `PendingWrite`. Preserve it and call
`recover(pending)` when the remote is readable. Recovery checks ancestry and
exact historical content, so a successful push is not duplicated even when
later mailbox commits have advanced the branch. A missing commit returns
`None`; the caller may then start a new publication attempt, which performs all
preconditions again.

The helper never force-pushes, merges mailbox histories, writes a cache or
projection, starts a background process, or treats an unverified local commit
as shared state.
