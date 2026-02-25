---
name: plan-promote-epic
description: >-
  Promote an epic to ready with explicit confirmation after readiness
  checks. Use when planning is complete.
---

# Promote epic to ready

## Inputs

- epic_id: Epic bead id to promote.
- beads_dir: Optional Beads store path.

## Readiness checks

- Epic has acceptance criteria and clear scope.
- Epic is executable in one of two ways:
  - has one or more child changeset beads, or
  - is itself the single executable changeset (sufficiently scoped, no child
    changesets).
- Changeset guardrails have been validated (run `plan-changeset-guardrails`
  first).
- Do not require child changesets when the epic itself is guardrail-sized.
- If the epic has exactly one child changeset, explicit decomposition rationale
  must be recorded before promotion.

## Steps

1. Show the epic and verify it is not already labeled `at:ready`.
1. List child changesets and confirm which are fully defined.
1. If there are no child changesets and the epic is single-changeset sized:
   - Add `at:changeset` to the epic.
   - Add `cs:ready` to the epic.
1. If there is exactly one child changeset:
   - Verify decomposition rationale is recorded in epic/child notes.
   - If rationale is missing, keep the epic as executable changeset or add the
     rationale before promotion.
1. If the epic is not single-changeset sized, create only the minimum child
   changesets needed for execution and reviewability.
1. Summarize the executable unit(s) for the user (child changesets or the epic
   itself).
1. Ask for explicit confirmation to promote.
1. On approval, add `at:ready` (do not use `at:draft`).
1. Promote each fully-defined `cs:planned` child changeset to `cs:ready`
   regardless of current dependency blockers.
1. Let dependency resolution determine runnability (`bd ready`) at worker time.

## Verification

- Epic includes `at:ready`.
- If the epic has child changesets, all fully-defined children are labeled
  `cs:ready`.
- If the epic has no child changesets, the epic itself is labeled `at:changeset`
  \+ `cs:ready`.
- Any one-child decomposition has explicit rationale in notes/description.
