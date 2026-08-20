# Atelier Project Policy Contract

## Purpose

Project policy connects one managed repository to one Atelier mailbox and
defines the authority and evidence rules that survive an agent session.

The initial contract deliberately supports one narrow delivery posture:

- one GitHub ticket,
- one remotely published candidate,
- one ready pull request,
- no merge, deployment, ticket mutation, or stack carving,
- and explicit operator acceptance.

Policy is strict YAML stored at `.atelier/policy.yaml` in the managed project.
At approval, Atelier pins the exact repository commit containing that file.
Unknown fields are invalid.

## Normative schema

The complete v0 policy shape is:

```yaml
schema: atelier.project-policy/v1

mailbox:
  remote: git@github.com:example/atelier-mailbox.git
  realm_id: personal
  canonical_branch: main
  project_id: prj_019f9a9e-0000-7000-8000-000000000001

repository:
  identity: github:example/project
  canonical_ref: refs/heads/main

ticket:
  provider: github
  allowed_states:
    - open
  require_no_blockers: true
  material_fields:
    - body
    - state
    - relationships

execution:
    capability: compris.implement-ticket/delegated-execution/v2
  delivery_outcome: ready_pr
  parallel_assignments: false

authority:
  allow:
    - repository.candidate.create
    - repository.candidate.push
    - pull_request.create
    - pull_request.update
    - review.reply
    - review.resolve

validation:
  required_commands:
    - just test
    - just lint

acceptance:
  actor: operator
  evidence:
    - candidate-remote-reachable
    - pull-request-head-current
    - pull-request-open
    - pull-request-mergeable
    - required-checks-pass
    - required-validation-reported
    - independent-review-current
    - unresolved-feedback-zero
```

Every mapping and sequence shown above is required. A sequence may be empty only
where its field semantics explicitly allow it. Values are case-sensitive.

## Field semantics

### Mailbox

`mailbox` tells project-scoped work mode how to locate shared Atelier state.

- `remote` is the Git remote URL. Credentials remain host-local.
- `realm_id` must match `atelier.yaml`.
- `canonical_branch` must match `atelier.yaml`.
- `project_id` must name the current repository in the mailbox project document.

A mismatch stops work before mailbox mutation.

### Repository

`repository.identity` is `github:<owner>/<repository>`.

`repository.canonical_ref` is the full remote ref from which current policy and
the implementation base are resolved. The initial contract supports
`refs/heads/<name>` only.

At approval, Atelier records:

- the repository identity,
- the exact commit containing `.atelier/policy.yaml`,
- and the policy path.

### Ticket

The initial provider is `github`.

`allowed_states` is a nonempty subset of:

- `open`.

`require_no_blockers` must be `true` in v0.

`material_fields` is a nonempty subset of:

- `body`,
- `state`,
- and `relationships`.

Before claim, Atelier reads those fields and records a canonical observation
digest in the claim and delegated invocation. Before every consequential
external mutation, delivery, and acceptance, it rereads them:

- an unchanged digest preserves the prior eligibility result;
- any material digest change denies the current delegated invocation before its
  next mutation;
- Atelier may freshly evaluate the changed ticket only before starting a new
  delegated invocation whose initial observation records the new digest;
- an ineligible or ambiguous fresh result keeps the work blocked;
- and a changed title alone is attribution drift, not contract drift.

A single invocation therefore has one immutable material ticket observation.
This keeps its terminal ticket identity truthful and makes every allowed drift
visible as a new invocation rather than an in-place reinterpretation.

The canonical digest input uses UTF-8 JSON with sorted keys and no insignificant
whitespace. `relationships` includes native blockers, blocked work, parent, and
sub-issue identifiers when the provider exposes them. Relationship sequences are
sorted by stable provider identifier before encoding.

### Execution

`execution.capability` is exactly
  `compris.implement-ticket/delegated-execution/v2`.

`execution.delivery_outcome` is exactly `ready_pr`.

`execution.parallel_assignments` is exactly `false`. The initial contract allows
only one active assignment per project; `true` is an unsupported value.

### Authority

`authority.allow` is the complete inheritable authority ceiling. Omitted actions
are denied.

The v0 vocabulary is:

- `repository.candidate.create`,
- `repository.candidate.push`,
- `pull_request.create`,
- `pull_request.update`,
- `review.reply`,
- and `review.resolve`.

The following actions are unsupported in v0 and therefore cannot appear:

- ticket mutation,
- dependency mutation,
- stack carving,
- merge,
- branch deletion,
- deployment,
- production mutation,
- destructive operations,
- and parent closure.

The effective authority for an action is the intersection of:

1. the approved policy's `authority.allow`,
1. the current policy's `authority.allow`,
1. the approved work authority,
1. the current invocation grant,
1. and host or native-system enforcement.

An ephemeral invocation may narrow authority. It cannot widen authority
inherited by a later session.

### Validation

`validation.required_commands` is an ordered sequence of nonempty command
strings. It may be empty only when the project has no local validation command.

Compris reports each command, result, exact candidate revision, and
observation time. These are recorded observations, not independently proven
facts. An operator may accept them under the `required-validation-reported`
predicate.

### Acceptance

`acceptance.actor` is exactly `operator` in v0.

`acceptance.evidence` is a nonempty subset of the finite evidence registry
below. An acceptance transition is valid only when every approved and currently
required predicate evaluates to `satisfied`.

The operator confirmation records:

- the invoking host's operator attribution,
- the exact delivery receipt,
- the exact candidate revision,
- the approved and current policy commits,
- each predicate verdict,
- and the canonical mailbox commit containing the acceptance.

This is cooperative attribution, not cryptographic non-repudiation.

## Evidence predicate registry

Each predicate has one authoritative source and exact evaluation.

### `candidate-remote-reachable`

- **Source:** the declared project Git remote.
- **Satisfied:** the delivered SHA is reachable from the delivered full remote
  ref after fetch.
- **Violated:** the ref exists but does not contain the SHA.
- **Unknown:** the remote or ref cannot be read.
- **Stale:** not applicable; a later ref advance still contains the delivered
  SHA.

### `pull-request-head-current`

- **Source:** live GitHub pull-request state.
- **Satisfied:** the PR head repository, full ref, and SHA equal the delivery.
- **Violated:** the PR refers to another repository or ref.
- **Unknown:** GitHub cannot be read.
- **Stale:** the PR head SHA changed after the receipt.

### `pull-request-open`

- **Source:** live GitHub pull-request state.
- **Satisfied:** the PR is open and not a draft.
- **Violated:** the PR is closed, merged, or still a draft.
- **Unknown:** GitHub cannot be read.
- **Stale:** not applicable.

### `pull-request-mergeable`

- **Source:** live GitHub conflict and merge-state status.
- **Satisfied:** GitHub reports the exact head mergeable and its current merge state
  does not block readiness. `UNSTABLE` does not fail this predicate by itself;
  configured required checks are evaluated separately.
- **Violated:** GitHub reports a conflict or a policy-blocked merge state.
- **Unknown:** conflict or merge-state status is unavailable or still being
  calculated.
- **Stale:** the PR head or exact comparison base changed after the observation.

### `required-checks-pass`

- **Source:** live required-check configuration plus check results for the exact PR
  head. Required identities are the exact context name plus optional GitHub App or
  ruleset integration identity obtained from effective branch protection and
  repository rulesets; observed results retain their check/status kind and
  integration identity.
- **Satisfied:** the required configuration was read and every named required
  check from its configured provider completed successfully; an empty configured
  set is satisfied.
- **Violated:** a named required check completed unsuccessfully.
- **Unknown:** required-check configuration or a named required result from its
  configured provider cannot be read, is missing, or is ambiguous.
- **Stale:** a named required result belongs to another PR head.

### `required-validation-reported`

- **Source:** the delivered receipt.
- **Satisfied:** every command required by the effective policy is reported as
  passed at the exact delivered SHA.
- **Violated:** a required command is reported as failed.
- **Unknown:** a required command or result is absent or unavailable.
- **Stale:** the receipt's candidate differs from the current delivery.

### `independent-review-current`

- **Source:** the delivered receipt plus normalized aggregate
  `review-code-change` audit evidence with structured finding dispositions.
- **Satisfied:** both records are clean, every finding has a non-unresolved
  disposition, and both are bound to the delivered SHA and comparison base.
- **Violated:** the result requires changes or retains an unresolved finding.
- **Unknown:** either record is missing, malformed, blocked, or contradictory.
- **Stale:** the delivered head, live PR base, or effective comparison base changed.

### `unresolved-feedback-zero`

- **Source:** live GitHub review, comment, and thread state plus the normalized
  audit-evidence dispositions bound to provider IDs and exact body digests.
- **Satisfied:** every nonempty top-level review or comment body has an explicit
  non-unresolved disposition and no unresolved material thread or receipt
  obligation remains. This predicate is an unconditional v0 acceptance guard,
  even when an older approval omitted it from `required_evidence`.
- **Violated:** an item is explicitly unresolved, the live review decision requires
  changes, or a material thread or receipt obligation remains unresolved.
- **Unknown:** thread-aware feedback cannot be read or a live body lacks a disposition.
- **Stale:** a disposition identifies missing feedback or an earlier body revision.

## Policy drift

At every authority fence, delivery, and acceptance, Atelier reads current policy
from `repository.canonical_ref`.

It does not attempt to classify the whole document as generally stricter or
looser. It combines fields deterministically:

- effective authority is the intersection of approved and current allow sets;
- effective validation commands are their ordered union;
- effective acceptance evidence is their set union;
- effective ticket states are their intersection;
- effective material ticket fields are their set union;
- and `require_no_blockers` is their boolean OR.

A change to mailbox identity, repository identity, canonical ref, ticket
provider, execution capability, delivery outcome, parallel-execution value,
acceptance actor, or schema is incompatible rather than ordered. It blocks the
dependent transition and requires a new work revision and approval.

Current policy can therefore tighten approved work but cannot silently widen it.

## Unsupported or malformed policy

Atelier fails closed when:

- the file is missing,
- YAML parsing fails,
- an unknown field appears,
- a required field is absent,
- a value is outside its finite vocabulary,
- the pinned approval commit cannot be read,
- current policy cannot be fetched,
- or deterministic approved/current combination is impossible.

Atelier reports the exact path and violation. It never rewrites project policy
automatically.
