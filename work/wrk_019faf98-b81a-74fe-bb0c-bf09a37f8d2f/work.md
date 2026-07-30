---
schema: atelier.work/v1
id: wrk_019faf98-b81a-74fe-bb0c-bf09a37f8d2f
title: Document the production dogfood lifecycle
project_id: prj_019faf81-a727-7f87-b3bf-ee92b37450eb
initiative_id: ini_019faf98-b7e3-7f60-818b-d34bc08bf3a4
status: active
revision: 2
dependencies: []
replaces: []
native_ticket:
  provider: github
  id: '781'
  url: https://github.com/shaug/atelier/issues/781
approval:
  approved_by: operator
  approved_at: '2026-07-29T20:52:04Z'
  revision: 2
  policy:
    repository: github:shaug/atelier
    commit: 7224a2396b5e289b80e59f4cf677959b0848ae75
    path: .atelier/policy.yaml
  authority_ceiling:
  - repository.candidate.create
  - repository.candidate.push
  - pull_request.create
  - pull_request.update
  - review.reply
  - review.resolve
  acceptance:
    mode: operator
    required_evidence:
    - candidate-remote-reachable
    - pull-request-head-current
    - pull-request-open
    - pull-request-mergeable
    - required-checks-pass
    - required-validation-reported
    - independent-review-current
    - unresolved-feedback-zero
claim:
  id: clm_019fb263-ca52-7151-ac62-33b1b1db7c9e
  worker_run_id: run_019fb263-ca88-73b6-963b-f73028ff9269
  inherited_receipt_id: rcp_019fb22a-202a-74a4-93e5-639f05cbe10e
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: 9dda9d21bf63e093b622f8701890f8602a378c96
  ticket_observation_digest: sha256:251c2d153267fe2ea2b30a2f519cd1045073a87a27c1877c5c806ecdb48e172a
  invocation_digest: sha256:712da46b3f924366a74de6ebd1bf6a182edd09e6b6c8e46af3f1576730ade8eb
  claimed_at: '2026-07-30T09:38:32.299602Z'
  host: codex
  checkpoint:
    sequence: 1
    continuation_token: Fbahp05-kTYNuvjU8oOGHrRyXDhjzZ8iPtHnKkLEXUY
    authorizations:
    - sequence: 1
      invocation_id: run_019fb263-ca88-73b6-963b-f73028ff9269
      phase: pre_external_mutation
      action: repository.candidate.create
      proposed_effect_digest: sha256:7965d29b5d109d4ccb932f3509d94ce936db13787036891f5f1ff940e6382819
      candidate_head: null
      candidate_remote_ref: null
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T09:43:45.644165Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: b072158d739952d687673bfdd9c371f2115597b3
    head_revision: b267cc67ae4ab34843e3d56d4bc67ad6888a21af
    pull_request: https://github.com/shaug/atelier/pull/793
    workspace_id: null
    published_at: '2026-07-30T08:33:05.258386Z'
blocking_message_id: null
attempt_receipt_id: rcp_019fb22a-202a-74a4-93e5-639f05cbe10e
delivery_receipt_id: null
acceptance: null
---
## Intent

Add one operator-facing reference that explains how separate planner, worker, fresh-task recovery, audit, and explicit acceptance tasks coordinate only through native GitHub state and the canonical Git mailbox.

## Rationale

The first v0 dogfood needs a durable, executable lifecycle reference that preserves accountability across task interruption without relying on transcript memory.

## Scope

Add skills/atelier/references/dogfood.md and link it from skills/atelier/SKILL.md.

## Non Goals

Do not change behavior, add automation, add provider mutation code, merge, deploy, close an issue, or include post-v0 #782/#783 work.

## Constraints

Preserve every authority boundary. Add no runtime, provider, daemon, or shared state. Do not claim in the reference that this dogfood run succeeded. Agent Scripts owns implementation. Required validation is exactly just lint and just test.

## Edge Cases

Cover interruption and recovery from a fresh task, stale or unknown evidence that must fail closed, and the distinctions among delivery, operator acceptance, and merge.

## Related Context

Use native GitHub issue #781 and the canonical Git mailbox as durable coordination state; keep the reference consistent with the existing planning, claiming, delegation, audit, host-boundary, mailbox-validation, and Git-mailbox-write references.

## Done Definition

The documentation is exact, executable, operator-facing, and consistent with the existing production planning, claiming, delegation, recovery, audit, and acceptance references.

## Verification Expectations

Run just lint and just test; preserve both results for an independent review of the exact candidate head.

## Review Shape Guidance

Deliver one coherent docs-only pull request.
