# Delegated implementation

Atelier delegates exactly one active, approved, claimed assignment to the
independently installed `agent-scripts:implement-ticket` skill. Agent Scripts
owns implementation and its transitive workflow. Atelier owns the approved
intent, invocation boundary, authority checkpoints, terminal validation, and
durable receipt.

## Preconditions

1. Complete `host-boundary.md` against the exact installed delegated-execution
   v2 bundle.
2. Read `claiming.md` and obtain the current claim fence and approval commit.
3. Capture a complete GitHub observation after a new read boundary.
4. Use `scripts/delegation.py` with `operation: prepare`. Provide an immutable local
   invocation path and a host-owned observation command that emits one fresh complete
   GitHub observation. Preparation builds and probes the one-shot stdin/stdout
   checkpoint adapter, writes the exact invocation locally, and atomically seals its
   canonical digest into the current claim. Pass that invocation unchanged to one
   fresh host worker.

Never copy `implement-ticket`, launch a substitute workflow, or persist
host-local task state in the mailbox. Starting the fresh worker is a host
operation; the script does not spawn Codex, a daemon, or a service.

## Checkpoints

The fresh worker must call the prepared checkpoint command before every
external mutation and after candidate publication, following the
dependency-owned v2 contract. For every request:

1. Run the exact prepared checkpoint command. The adapter establishes a new read
   boundary, executes the sealed host observation command, validates the resulting
   complete observation, and reads exactly one worker request from stdin.
2. The adapter atomically rereads the current claim, current policy and canonical
   base, ticket, repository, sequence, and authority before deciding.
3. Read exactly one checkpoint response from stdout.
4. Return the response unchanged. An `allow` rotates the continuation token and
   advances exactly one durable mailbox sequence. A `deny` consumes neither.
5. Treat `candidate_published` as an acknowledgement only when the exact remote
   ref contains the declared head.

Do not cache observations, mint replacement fences, widen the six v0 authority
actions, or acknowledge deployment. Atelier v0 accepts only `ready_pr`,
`blocked`, and `requires_epic`.

## Terminal result

Invoke `scripts/delegation.py` with `operation: finalize`, the unchanged sealed
invocation, the exact current fence, the worker result, and another fresh complete
observation. Atelier requires the result to report no tracker mutation and to
match the still-open current native ticket before recording a receipt.

- `ready_pr` requires one ordinary open, non-draft, mergeable pull request whose
  base, head, remote candidate, checks, validation, independent review,
  feedback, and required acceptance evidence all bind to the exact candidate.
- `blocked` preserves any acknowledged candidate. If the exact push succeeded but
  its `candidate_published` acknowledgement failed, the blocked result may recover
  that remotely reachable candidate only when it matches the sealed invocation and
  the ledger's final authorized push head and remote ref. A replacement candidate
  recovered this way may omit an inherited pull request that could not be
  acknowledged without fresh exact PR authority; the predecessor receipt preserves
  that prior candidate and PR history, while the blocked receipt preserves the
  denied-acknowledgement obligations. Atelier binds the candidate and immutable
  blocked receipt atomically, records one unresolved planner decision, and retains
  mutation ownership. A later attempt still needs fresh exact PR authority before
  it can publish or restore PR metadata.
- `requires_epic` is recorded as a blocked attempt for planner action. Atelier
  does not invoke `implement-epic` from delegated work.

Every terminal result records exactly one immutable attempt receipt.
`ready_pr` also records that receipt as the delivery receipt. Delivery is not
operator acceptance, merge, deployment, or ticket completion.

## JSON request boundary

The CLI accepts one JSON object containing:

- `operation`: `prepare`, `checkpoint`, or `finalize`;
- `mailbox`: canonical `remote` and `branch`;
- `work_id`, `approved_commit`, `policy_target`, `host_target`;
- `observation_path` and `observation_not_before`;
- for `prepare`, `checkpoint_invocation_path` and the host-owned
  `observation_command`; and
- the remaining operation-specific fence, invocation, checkpoint request, result,
  and timestamps.

Unknown, missing, stale, contradictory, or unverifiable state fails closed
before a mailbox success is reported.
