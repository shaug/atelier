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
  id: clm_019fb2ea-dd15-7539-97bd-c3a9d12d1708
  worker_run_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
  inherited_receipt_id: rcp_019fb2ea-1fdc-79ea-88ec-dda7afacc4a7
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: e339a669a8fd311d2fafb648a825788b02c88494
  ticket_observation_digest: sha256:9f428b649faa032ede6722ed7f35d96b48d12b97bff1a2bcd16bab7c0185bed5
  invocation_digest: sha256:2e7619739575a0fe77e2cec63b4cad9a945285530ae10c84b1b4ce215858ce90
  claimed_at: '2026-07-30T12:06:29.757380Z'
  host: codex
  checkpoint:
    sequence: 2
    continuation_token: TdKbDQOOdatGT_70bYrY8SDZ7eBJFZ_WQdC04gV3dtA
    authorizations:
    - sequence: 1
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: repository.candidate.create
      proposed_effect_digest: sha256:7cccf2209745ac872d6611847ee8bc7ee8c38a7a01f42fbbc302660d08d0bb28
      candidate_head: null
      candidate_remote_ref: null
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:09:50.797069Z'
    - sequence: 2
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:bd6dc1561bc45f0948d3a0346e79874fdeeed45acd1f8b72bf2669ac3dd01d61
      candidate_head: 480830c9812e06b8a0d60206791d7d5c0ea70d87
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:18:18.651158Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: 9dda9d21bf63e093b622f8701890f8602a378c96
    head_revision: e6e87c7c8b666ff7467f96538078377ef5510de9
    pull_request: null
    workspace_id: null
    published_at: '2026-07-30T12:04:04.994517Z'
blocking_message_id: null
attempt_receipt_id: rcp_019fb2ea-1fdc-79ea-88ec-dda7afacc4a7
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
