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
  id: clm_019fb015-ef90-7ed0-8fab-9768b255aa2d
  worker_run_id: run_019fb015-ee9a-77de-9062-990f107e9bbf
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: 7224a2396b5e289b80e59f4cf677959b0848ae75
  ticket_observation_digest: sha256:923b7a5018d64b5d6090398dd6f4cea7bfdec31a25b49d2561b03ab8824c9e81
  invocation_digest: sha256:d6278ab5a3b254b592715b5ab7e6292aff6ef014218dcbc5fbf7e326e8502d78
  claimed_at: '2026-07-29T22:54:15.285284Z'
  host: codex
  checkpoint:
    sequence: 2
    continuation_token: 4r4q6Jbr918VNUgqhvrNqa2V4mgz41ZqZCjeDdTEWCU
    authorizations:
    - sequence: 1
      invocation_id: run_019fb015-ee9a-77de-9062-990f107e9bbf
      phase: pre_external_mutation
      action: pull_request.create
      proposed_effect_digest: sha256:1c496432912a463292317bf84f68a82724545706dc90d8f824959c7f0c05f710
      candidate_head: fc9022ffd1b47a74a1b85580bca5dc4a504cef78
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      acknowledged_candidate_head: null
      recorded_at: '2026-07-29T22:59:40.305852Z'
    - sequence: 2
      invocation_id: run_019fb015-ee9a-77de-9062-990f107e9bbf
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:4eb25df0fe9ae2e9be2c274551e823581cf69db6bdf008a67f49dd8498742b4a
      candidate_head: fc9022ffd1b47a74a1b85580bca5dc4a504cef78
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      acknowledged_candidate_head: null
      recorded_at: '2026-07-29T23:04:57.677972Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: 7224a2396b5e289b80e59f4cf677959b0848ae75
    head_revision: fc9022ffd1b47a74a1b85580bca5dc4a504cef78
    pull_request: null
    workspace_id: null
    published_at: '2026-07-29T22:21:56Z'
blocking_message_id: null
attempt_receipt_id: rcp_019fb015-7f52-7145-b7d5-6b49f4fb58f4
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
