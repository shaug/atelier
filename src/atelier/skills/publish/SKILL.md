# Skill: publish

## Purpose

Provide a deterministic workflow for publishing, persisting, and finalizing
Atelier workspaces.

## Supported Operations

- publish: run required checks, prepare commits, and publish per `PERSIST.md`.
- persist: save progress per `PERSIST.md` without finalization.
- finalize: publish first, then integrate and tag per `PERSIST.md`.

## Owned State

- Workspace git state (commits, branches, tags) required to publish/finalize.
- Workspace finalization tag `atelier/<branch-name>/finalized`.

## Invariants

- Required checks in `PROJECT.md`, `SUCCESS.md`, or repo `AGENTS.md` must run
  before publish/persist/finalize unless the user explicitly overrides.
- Workspace working tree must be clean before and after publish operations.
- Integration steps must follow `PERSIST.md` exactly.
- Finalization must not occur without explicit instruction.

## Prohibited Actions

- Do not invoke `atelier` to mutate state.
- Do not modify skill files or templates.
- Do not bypass required checks without explicit user approval.

## Allowed Verification Calls

- `atelier describe --format=json`
- `atelier list --format=json`

## Notes

When a publish workflow requires pull request operations, delegate to the
`github` skill for PR creation or updates.
