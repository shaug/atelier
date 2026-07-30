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
  id: clm_019fb165-c28f-7762-a122-b7666a334fe8
  worker_run_id: run_019fb165-c2d7-783e-95bc-240690aaf69b
  inherited_receipt_id: null
  work_revision: 2
  approved_commit: 8e4e96e7e50888412fcf11fb7a64e74fedc88950
  policy_commit: b072158d739952d687673bfdd9c371f2115597b3
  ticket_observation_digest: sha256:c8ab154a17b92c7f380e89830c0ef7be3475500a6a1cee94656d6d361f98eb5f
  invocation_digest: sha256:45cfa2f8b4bfeb8b298599906e405d00eeaab71d1df569c36c6287ad29e9f12f
  claimed_at: '2026-07-30T05:01:03.277764Z'
  host: codex
  checkpoint:
    sequence: 3
    continuation_token: aqJpQp06t848Fbct4Szj7Gpfl4vgy68lV0K6yUzIsA4
    authorizations:
    - sequence: 1
      invocation_id: run_019fb165-c2d7-783e-95bc-240690aaf69b
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:129109c21bd54778bddf2e177dd454a23549e1256553adda89b59022996ec5a4
      candidate_head: 5b84aad8a4df688f2e3c8de6267e3e4e957d4701
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T05:14:21.241801Z'
    - sequence: 2
      invocation_id: run_019fb165-c2d7-783e-95bc-240690aaf69b
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:f68bd3f03f5d111674dc5dfeb79d6b3ebbfc84d5bf587c5f4fa8ff6aa321ea1a
      candidate_head: 5b84aad8a4df688f2e3c8de6267e3e4e957d4701
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T05:20:42.359472Z'
    - sequence: 3
      invocation_id: run_019fb165-c2d7-783e-95bc-240690aaf69b
      phase: pre_external_mutation
      action: repository.candidate.push
      proposed_effect_digest: sha256:745cc8aa540a749137939ce9d484ff3f733e2250e9b0ae01c9cb8bc8b5682b0a
      candidate_head: 904314c835a870fe9dd0a0d75f4ff1e23e78cad8
      candidate_remote_ref: refs/heads/scott/issue-781-dogfood-guide
      candidate_pull_request: null
      acknowledged_candidate_head: null
      recorded_at: '2026-07-30T06:42:35.442261Z'
  candidate:
    repository: github:shaug/atelier
    remote: origin
    remote_url: https://github.com/shaug/atelier.git
    remote_ref: refs/heads/scott/issue-781-dogfood-guide
    base_revision: b072158d739952d687673bfdd9c371f2115597b3
    head_revision: 904314c835a870fe9dd0a0d75f4ff1e23e78cad8
    pull_request: null
    workspace_id: null
    published_at: '2026-07-30T06:57:26.442429Z'
blocking_message_id: msg_019fb1d0-56e1-7dfd-86b8-299674717254
attempt_receipt_id: rcp_019fb1d0-56e1-755b-9d8e-7d6fdaad0164
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
