# Skill: tickets

## Purpose

Provide deterministic workflows for associating workspaces with tickets and
reading or updating ticket metadata.

## Supported Operations

- read: fetch ticket metadata for a referenced ticket ID.
- associate: record ticket references in workspace config.
- update: apply allowed ticket state changes when explicitly requested.

## Owned State

- Workspace ticket references stored in config metadata.
- External ticket metadata when updates are requested.

## Invariants

- Ticket identifiers must be explicit and validated.
- Workspace ticket references must reflect user-provided IDs.
- External updates must be confirmed before execution.
- Delegate provider-specific issue operations to the `github-issues` or `linear`
  skill.

## Prohibited Actions

- Do not invoke `atelier` to mutate state.
- Do not modify tickets without an explicit user instruction.
- Do not alter unrelated workspace configuration.

## Allowed Verification Calls

- `atelier describe --format=json`
- `atelier list --format=json`
