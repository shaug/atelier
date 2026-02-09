---
name: plan_promote_epic
description: >-
  Promote a draft epic to ready with explicit confirmation after readiness
  checks. Use when planning is complete.
---

# Promote epic to ready

## Inputs

- epic_id: Draft epic bead id to promote.
- beads_dir: Optional Beads store path.

## Readiness checks

- Epic has acceptance criteria and clear scope.
- Epic contains at least one changeset bead.
- Changeset guardrails have been validated (run `plan_changeset_guardrails`
  first).

## Steps

1. Show the epic and verify it is labeled `at:draft`.
1. List child changesets and confirm they are planned/ready.
1. Summarize the epic and changesets for the user.
1. Ask for explicit confirmation to promote.
1. On approval, remove `at:draft` and add `at:ready`.

## Verification

- Epic no longer has `at:draft`.
- Epic includes `at:ready`.
