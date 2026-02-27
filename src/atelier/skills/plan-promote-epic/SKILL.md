---
name: plan-promote-epic
description: >-
  Promote an epic to open with explicit confirmation after readiness checks.
  Use when planning is complete.
---

# Promote Epic to Open

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
- Exactly one child changeset is a planning anti-pattern and must be resolved
  before promotion.

## Steps

1. Show the epic and verify its status is `deferred`.
1. List child changesets and confirm which are fully defined.
1. If there are no child changesets and the epic is single-changeset sized:
   - Add `at:changeset` to the epic.
   - Keep execution state in status only (`deferred` now, `open` on promotion).
1. If there is exactly one child changeset:
   - Do not promote until the anti-pattern is resolved.
   - Resolve by either collapsing to the epic as executable changeset, or
     decomposing into at least two child changesets for documented multi-step
     execution needs.
1. If the epic is not single-changeset sized, create only the minimum child
   changesets needed for execution and reviewability.
1. Summarize the executable unit(s) for the user (child changesets or the epic
   itself).
1. Ask for explicit confirmation to promote.
1. On approval, set epic status to `open`.
1. Promote each fully-defined child changeset from `deferred` to `open`
   regardless of current dependency blockers (dependency graph still gates
   runnability).
1. Let dependency resolution determine runnability (`bd ready`) at worker time.

## Verification

- Epic status is `open`.
- If the epic has child changesets, all fully-defined children are status
  `open`.
- If the epic has no child changesets, the epic is the executable leaf work unit
  (`at:changeset`) and status `open`.
- No one-child decomposition remains at promotion time.
