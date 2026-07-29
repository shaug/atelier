---
schema: atelier.work/v1
id: wrk_019faf98-b81a-74fe-bb0c-bf09a37f8d2f
title: Document the production dogfood lifecycle
project_id: prj_019faf81-a727-7f87-b3bf-ee92b37450eb
initiative_id: ini_019faf98-b7e3-7f60-818b-d34bc08bf3a4
status: draft
revision: 1
dependencies: []
replaces: []
native_ticket:
  provider: github
  id: '781'
  url: https://github.com/shaug/atelier/issues/781
approval: null
claim: null
blocking_message_id: null
attempt_receipt_id: null
delivery_receipt_id: null
acceptance: null
---
## Intent

Add one operator-facing reference that explains how separate planner, worker, recovery, audit, and explicit acceptance tasks coordinate through native GitHub state and the canonical Git mailbox.

## Rationale

The first v0 dogfood needs a durable, executable lifecycle reference that preserves accountability across fresh tasks.

## Scope

Add skills/atelier/references/dogfood.md and link it from skills/atelier/SKILL.md.

## Non Goals

Do not change behavior, add automation or provider mutation code, merge, deploy, close issues, or include post-v0 #782/#783 work.

## Constraints

Preserve every authority boundary; add no runtime, provider, daemon, or shared state; do not claim this dogfood run succeeded; Agent Scripts owns implementation; validate with just lint and just test.

## Edge Cases

Cover interruption and fresh-task recovery, stale or unknown evidence, and the distinction between delivery, acceptance, and merge.

## Related Context

Keep the reference consistent with the existing planning, claiming, delegation, audit, host-boundary, and Git-mailbox references.

## Done Definition

The documentation is exact, executable, operator-facing, and consistent with the existing production lifecycle references.

## Verification Expectations

Run just lint and just test and preserve their results for independent review.

## Review Shape Guidance

Keep this as one coherent docs-only pull request.
