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
    sequence: 10
    continuation_token: 62UGsmCmpTFDty0WD21lBXe6wkBwlGuOSVPmbn0Mf6s
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
    - sequence: 3
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:fbba36b11ec3fc28c74ca6eff29ec86e5f882811b2d35c224c3024a60d87bfda
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:30:21.094668Z'
    - sequence: 4
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: candidate_published
      action: repository.candidate.push
      proposed_effect_digest: sha256:fbba36b11ec3fc28c74ca6eff29ec86e5f882811b2d35c224c3024a60d87bfda
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      recorded_at: '2026-07-30T12:32:24.854585Z'
    - sequence: 5
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: pull_request.update
      proposed_effect_digest: sha256:2b20173148651846d0a5add5fea6ece2b08ba2a81641bb280a50d263cd83d241
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:33:04.477777Z'
    - sequence: 6
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:5eb81d32043f7f1f9a8c18fc1ed8f8cd7690bc8774b0e933f974aa078526e835
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:33:56.351469Z'
    - sequence: 7
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: candidate_published
      action: repository.candidate.push
      proposed_effect_digest: sha256:5eb81d32043f7f1f9a8c18fc1ed8f8cd7690bc8774b0e933f974aa078526e835
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      recorded_at: '2026-07-30T12:34:40.362327Z'
    - sequence: 8
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: pull_request.update
      proposed_effect_digest: sha256:e7d72bebffea62f799483c55c0bde569940caaeedda811a6bdbea4460efe1af5
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:38:58.624253Z'
    - sequence: 9
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:dd157f5b751f5391ca84478cbb7a773e6cfb29904109dace751d424dd2abb108
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T12:39:49.524767Z'
    - sequence: 10
      invocation_id: run_019fb2ea-dd4f-7390-a236-a74023c632f9
      phase: candidate_published
      action: repository.candidate.push
      proposed_effect_digest: sha256:dd157f5b751f5391ca84478cbb7a773e6cfb29904109dace751d424dd2abb108
      candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      recorded_at: '2026-07-30T12:40:39.699624Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: e339a669a8fd311d2fafb648a825788b02c88494
    head_revision: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
    pull_request: null
    workspace_id: null
    published_at: '2026-07-30T12:40:39.699624Z'
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
