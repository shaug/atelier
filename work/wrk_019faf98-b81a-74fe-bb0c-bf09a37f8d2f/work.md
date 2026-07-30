---
schema: atelier.work/v1
id: wrk_019faf98-b81a-74fe-bb0c-bf09a37f8d2f
title: Document the production dogfood lifecycle
project_id: prj_019faf81-a727-7f87-b3bf-ee92b37450eb
initiative_id: ini_019faf98-b7e3-7f60-818b-d34bc08bf3a4
status: blocked
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
  id: clm_019fb207-d29f-78f8-832c-7aca86e4db06
  worker_run_id: run_019fb207-d2e4-728b-9630-e3f755fed50f
  inherited_receipt_id: null
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: b072158d739952d687673bfdd9c371f2115597b3
  ticket_observation_digest: sha256:c8ab154a17b92c7f380e89830c0ef7be3475500a6a1cee94656d6d361f98eb5f
  invocation_digest: sha256:0a4fc46bfa4f7519ba0d93ada9a611afdd457b421d8d1db8d055fd8914edc387
  claimed_at: '2026-07-30T07:58:33.955580Z'
  host: codex
  checkpoint:
    sequence: 1
    continuation_token: usIS4y5zKp6nKtdQw7P8NJEqtBUZPsuX-B-1nVLK6NY
    authorizations:
    - sequence: 1
      invocation_id: run_019fb207-d2e4-728b-9630-e3f755fed50f
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:7d7bb273cc71f6b352d4a93fd87f9042bbd1149b482b23a5e8f1031740d7c45c
      candidate_head: b267cc67ae4ab34843e3d56d4bc67ad6888a21af
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T08:16:12.052434Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: b072158d739952d687673bfdd9c371f2115597b3
    head_revision: b267cc67ae4ab34843e3d56d4bc67ad6888a21af
    pull_request: null
    workspace_id: null
    published_at: '2026-07-30T08:23:05.135410Z'
blocking_message_id: msg_019fb21e-bf08-7e32-aa8b-1f972fbd1ccb
attempt_receipt_id: rcp_019fb21e-bf08-700b-9260-20d9b7d5ffbe
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
