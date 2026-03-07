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
- Promotion preview shows the full epic contract plus the full child changeset
  contract(s) in deterministic order.
- The preview includes description, notes, acceptance criteria, dependencies,
  and related-context references for the epic and each child.
- Missing required detail sections are surfaced explicitly before any
  confirmation prompt.
- Do not require child changesets when the epic itself is guardrail-sized.
- If the epic has exactly one child changeset, explicit decomposition rationale
  must be recorded before promotion.

## Steps

1. Show the epic and verify its status is `deferred`.
1. List child changesets and confirm which are fully defined.
1. Render the promotion preview in deterministic order:
   - epic first, then child changesets sorted by bead id.
   - For the epic and for each child, show:
     - description
     - notes
     - acceptance criteria
     - dependencies
     - related-context references
   - If any required section is absent or placeholder-only, print
     `Missing detail sections: ...` for that epic/child before asking the user
     anything.
1. If there are no child changesets and the epic is single-changeset sized:
   - Keep execution state in status only (`deferred` now, `open` on promotion).
   - The epic is a changeset by graph inference (leaf in its own hierarchy).
1. If there is exactly one child changeset:
   - Verify decomposition rationale is recorded in epic/child notes.
   - If rationale is missing, keep the epic as executable changeset or add the
     rationale before promotion.
1. If the epic is not single-changeset sized, create only the minimum child
   changesets needed for execution and reviewability.
1. Summarize the executable unit(s) for the user only after the full preview is
   shown (child changesets or the epic itself).
1. Ask for explicit confirmation to promote only after the full preview and any
   missing-detail warnings are visible.
1. On approval, set epic status to `open`.
1. Promote each fully-defined child changeset from `deferred` to `open`
   regardless of current dependency blockers (dependency graph still gates
   runnability).
1. Let dependency resolution determine runnability (`bd ready`) at worker time.

## Verification

- Confirmation prompt was preceded by the full epic and child detail preview.
- Preview ordering is deterministic: epic first, then children by bead id.
- Missing detail sections are shown explicitly instead of being skipped
  silently.
- Epic status is `open`.
- If the epic has child changesets, all fully-defined children are status
  `open`.
- If the epic has no child changesets, the epic is the executable leaf work unit
  (changeset by graph inference) and status `open`.
- Any one-child decomposition has explicit rationale in notes/description.
