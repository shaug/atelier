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
  id: clm_019fafac-4f9b-7a30-a154-2374cf2de88b
  worker_run_id: run_019fafac-4fe5-796f-aa10-130f87141949
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: 7224a2396b5e289b80e59f4cf677959b0848ae75
  ticket_observation_digest: sha256:923b7a5018d64b5d6090398dd6f4cea7bfdec31a25b49d2561b03ab8824c9e81
  invocation_digest: sha256:28b69b0e56788d127766882fe4b58e70a8653a069488dbb7370a3cb1e314e5f8
  claimed_at: '2026-07-29T20:58:53Z'
  host: codex
  checkpoint:
    sequence: 3
    continuation_token: w1Pd6ouimF2eAmfXzyC96HeJNvrv1IQVBM5fQlq9tnI
    authorizations:
    - sequence: 1
      invocation_id: run_019fafac-4fe5-796f-aa10-130f87141949
      phase: pre_external_mutation
      action: repository.candidate.create
      proposed_effect_digest: sha256:1d892e85098f457ab53c7fd840a4434010069b99e841413744581594998108f2
      candidate_head: null
      candidate_remote_ref: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-29T21:11:58.567240Z'
    - sequence: 2
      invocation_id: run_019fafac-4fe5-796f-aa10-130f87141949
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:7abbe6e341f5a9398fada953449090c7793e3ba2a9e9aa6ebcdf52a7ab08f014
      candidate_head: fc9022ffd1b47a74a1b85580bca5dc4a504cef78
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      acknowledged_candidate_head: null
      recorded_at: '2026-07-29T21:48:27.719220Z'
    - sequence: 3
      invocation_id: run_019fafac-4fe5-796f-aa10-130f87141949
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:f4c0a146309c14c7bf762e1148f36adbbb2616a724b3245758548e407475cc9a
      candidate_head: fc9022ffd1b47a74a1b85580bca5dc4a504cef78
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      acknowledged_candidate_head: null
      recorded_at: '2026-07-29T21:55:16.342094Z'
  candidate: null
blocking_message_id: null
attempt_receipt_id: null
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
