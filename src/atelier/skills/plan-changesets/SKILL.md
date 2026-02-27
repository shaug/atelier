---
name: plan-changesets
description: >-
  Create changeset beads under an epic with guardrails for reviewable sizing.
---

# Plan changesets

Only use this when an epic should be decomposed. If the epic itself is already
within guardrails, keep the epic as the executable changeset instead of creating
children.

Capture new executable work immediately as deferred changesets
(`status=deferred`) when issues are actionable. Do not wait for approval to
create/edit deferred work.

## Inputs

- epic_id: Parent epic bead id.
- changesets: Ordered list of changeset titles and acceptance criteria.
- guardrails: Size and decomposition rules (line counts, subsystem splits).
- no_export: Optional per-bead opt-out from default auto-export.
- beads_dir: Optional Beads store path.

## Guardrails

- Separate renames from behavioral changes.
- Prefer additive-first changesets.
- Keep changesets reviewable (~200–400 LOC; split when >800 LOC).
- Avoid one-child decomposition by default. If a split would produce exactly one
  child changeset, keep the epic as the executable changeset unless you record
  explicit decomposition rationale.
- Keep tests with the nearest production change.
- Ask for an estimated LOC range per changeset and confirm approval when a
  changeset exceeds ~800 LOC (unless purely mechanical).
- If a changeset is trending >400 LOC, consider splitting before implementation.
- Record the LOC estimate and any explicit approval in notes (use `--notes` or
  `--append-notes`, not `--estimate`).

## Steps

1. For each changeset, create a bead with the script:
   - `python skills/plan-changesets/scripts/create_changeset.py --epic-id <epic_id> --title "<title>" --acceptance "<acceptance>" [--status deferred|open] [--description "<scope/guardrails>"] [--notes "<notes>"] [--beads-dir "<beads_dir>"] [--no-export]`
1. If decomposition would produce exactly one child changeset, stop and either:
   - keep the epic as the executable changeset, or
   - record explicit decomposition rationale in epic/changeset notes before
     creating the child.
1. Default new changesets to `status=deferred`; promote to `status=open` only
   via the explicit promotion flow.
1. Capture an estimated LOC range and record it in notes.
1. If a changeset violates guardrails (especially >800 LOC), pause and request
   explicit approval; record the approval decision in notes.
1. Record guardrails in the changeset description or notes.
1. The script creates the bead, applies auto-export when enabled by project
   config, and prints non-fatal retry instructions if export fails.

## Verification

- Changeset beads exist under the epic (leaf work beads in the epic's progeny).
- Decomposition happened only when needed for scope/dependency/reviewability.
- Any one-child decomposition has explicit rationale recorded in notes or
  description.
- When auto-export is enabled and not opted out, each changeset gets its own
  exported external ticket link.
