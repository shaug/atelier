---
name: plan-create-epic
description: >-
  Create a new epic bead with acceptance criteria and planning fields for
  changeset work.
---

# Plan create epic

When a concrete issue is identified, capture it as a deferred epic immediately.
Do not request approval to create or edit deferred beads.

## Inputs

- title: Epic title.
- scope: Short scope summary.
- acceptance: Acceptance criteria.
- changeset_strategy: Guardrails or decomposition rules.
- design: Optional design notes or links.
- required_refinement: Optional bool that marks the epic as refinement-required.
- refinement_approval_source: Approval source (`operator|project_policy`) when
  required refinement is enabled.
- refinement_approved_by: Principal id for required refinement approval.
- refinement_approved_at: Approval timestamp for required refinement.
- no_export: Optional per-bead opt-out from default auto-export.
- beads_dir: Optional Beads store path.
- repo_dir: Optional repo root override. Defaults to `./worktree` then cwd.

## Steps

1. Create the epic with the script:
   - `python skills/plan-create-epic/scripts/create_epic.py --title "<title>" --scope "<scope>" --acceptance "<acceptance>" [--changeset-strategy "<changeset_strategy>"] [--design "<design>"] [--required-refinement --refinement-approval-source operator --refinement-approved-by "<principal>" --refinement-approved-at "<timestamp>"] [--beads-dir "<beads_dir>"] [--repo-dir "<repo_dir>"] [--no-export]`
   - This is the canonical top-level executable-work creation path; it sets both
     `issue_type=epic` and the required `at:epic` discovery label.
   - The script is a thin planner wrapper over
     `atelier.store.CreateEpicRequest`; planner code should not compose raw
     `bd create` argv for this flow.
1. Refine the epic into the executable-path authoring contract immediately:
   - Record explicit `intent`, `rationale`, `non_goals`, `constraints`,
     `edge_cases`, and `related_context` fields in description/notes/design.
   - Use acceptance criteria as the done definition, or add
     `done_definition: ...` when completion needs sharper wording.
   - If there is no broader bead context, write
     `related_context: none identified.`
1. The script creates the bead, applies auto-export when enabled by project
   config, sets status to `deferred`, and prints non-fatal retry instructions if
   export fails.
1. If `--required-refinement` is set, approval evidence fields are required and
   the script appends an authoritative `planning_refinement.v1` block.
1. If promotion is needed, use `plan-promote-epic`; promotion from `deferred` to
   `open` is the approval gate.
1. Use `--notes` or `--append-notes` for addendums instead of rewriting the
   description.
1. See [Planner Store Migration Contract] for the exact planner-side store
   boundary and the remaining deferred preview gap.

## Verification

- Epic is created with `at:epic` label (required for epic discovery/indexing).
- Epic is created with `issue_type=epic`.
- Epic status is `deferred` until explicit promotion.
- Acceptance criteria stored in the acceptance field.
- Epic description/notes/design capture the required planner authoring contract
  before promotion.
- Required refinement requests persist explicit approval evidence in
  `planning_refinement.v1` note metadata.
- When auto-export is enabled and not opted out, `external_tickets` is updated
  with `direction=exported` and `sync_mode=export`.
- If startup diagnostics report identity drift, remediation is deterministic:
  `bd update <epic-id> --type epic --add-label at:epic`.

<!-- inline reference link definitions. please keep alphabetized -->

[planner store migration contract]: ../../../../docs/planner-store-migration-contract.md
