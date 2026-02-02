# Molecules Integration Proposal

## Summary

Introduce optional molecules as a workflow layer that can be attached to epics
and changesets without changing Atelier's core Beads model. Molecules are
opt-in: projects may ignore them entirely, while projects that want structured
review or QA loops can attach a molecule to each changeset at the point it
enters review.

## Goals

- Keep molecules optional and additive (no hard dependency for basic planning
  and work).
- Store molecule state in Beads using minimal, stable fields.
- Allow projects to define default molecules for changeset workflows.
- Expose molecule state in `atelier status` when present.

## Non-goals

- Build a full molecules runtime inside Atelier.
- Require molecule definitions to be stored in Beads.
- Auto-migrate existing projects or changesets.

## Proposed Data Model

Represent molecule attachments as structured fields in bead descriptions. Prefer
simple key/value lines to preserve compatibility with existing Beads stores.

Recommended fields (changeset beads):

- `molecule_id: <id or slug>`
- `molecule_state: <state>`
- `molecule_step: <step>`
- `molecule_updated_at: <timestamp>`

Optional fields (epic beads):

- `molecule_id: <id or slug>`
- `molecule_state: <state>`

Labels are optional. If needed for filtering, use a single label prefix:

- `mol:<slug>`

## Workflow Integration

1. Planner/worker creates changeset beads as usual.
1. When a changeset enters review (`draft-pr` or `in-review`), attach a
   molecule:
   - Set `molecule_id` and initial `molecule_state`.
   - Record initial step metadata if the molecule runtime exposes it.
1. As the molecule progresses (for example, “address feedback”, “retest”,
   “resubmit”), update the bead fields.
1. When the PR merges, clear or archive molecule fields.

## Config Surface

Allow a project-level default molecule in config:

- `project.molecules.default_changeset: <slug>`
- `project.molecules.enabled: true|false`

If unset, no molecule is attached automatically.

## Status & Observability

`atelier status` should surface molecule fields when present:

- For epics: `molecule_state`
- For changesets: `molecule_state`, `molecule_step`

## Migration Path

- No migration required for existing projects.
- If a project already uses molecules, configure
  `project.molecules.enabled=true` and set the default slug.
- Existing changesets can opt in by setting `molecule_id` manually or via a
  skill.

## Open Questions

- Should molecule fields be stored in notes instead of description lines?
- Do we need a dedicated `molecules_attach` skill to standardize updates?
- Should molecules be allowed on epics, or only on changesets?
