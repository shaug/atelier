---
schema: atelier.work/v1
id: wrk_019faf98-b81a-74fe-bb0c-bf09a37f8d2f
title: Document the production dogfood lifecycle
project_id: prj_019faf81-a727-7f87-b3bf-ee92b37450eb
initiative_id: ini_019faf98-b7e3-7f60-818b-d34bc08bf3a4
status: accepted
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
claim: null
blocking_message_id: null
attempt_receipt_id: rcp_019fb30f-9481-74a0-b433-927f05a76d80
delivery_receipt_id: rcp_019fb30f-9481-74a0-b433-927f05a76d80
acceptance:
  receipt_id: rcp_019fb30f-9481-74a0-b433-927f05a76d80
  accepted_by: operator
  accepted_at: '2026-07-30T13:23:40Z'
  policy_commit: e339a669a8fd311d2fafb648a825788b02c88494
  candidate_revision: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
  evidence:
    candidate-remote-reachable: satisfied
    pull-request-head-current: satisfied
    pull-request-open: satisfied
    pull-request-mergeable: satisfied
    required-checks-pass: satisfied
    required-validation-reported: satisfied
    independent-review-current: satisfied
    unresolved-feedback-zero: satisfied
  audit_evidence:
    schema: atelier.audit-evidence/v1
    review:
      mechanism: review-code-change
      verdict: clean
      candidate_revision: 0e677e46fb0cb9e80ca2bcc6f943ce8eb756fd45
      comparison_base_revision: e339a669a8fd311d2fafb648a825788b02c88494
      observed_at: '2026-07-30T12:54:53Z'
      findings: []
    feedback_dispositions: []
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
