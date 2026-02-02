# Beads conventions (Atelier)

Use these conventions when creating or updating Beads in Atelier-managed
projects. Stick to core Beads fields so existing Beads repos remain compatible.

## Labels

- `at:epic` for workspace epics
- `at:changeset` for changeset tasks
- `at:task` / `at:subtask` for supporting work
- `at:draft` for epics that are not claimable
- `at:hooked` for epics claimed by an agent
- `at:message` for message beads

## Status

- Prefer Beads core statuses (`open`, `in_progress`, `closed`).
- If custom statuses are not supported, represent `hooked` / `pinned` as labels
  and keep status at `open`.

## Core fields

- Use `--acceptance` for acceptance criteria (do not embed in description).
- Use `--design` for design notes (link or embed design docs).
- Use `--estimate` for time estimates (minutes).
- Use `--priority` (default P2 unless specified).
- Use `--notes` / `--append-notes` for addendums without rewriting descriptions.

## Description fields

Use key: value lines in descriptions for structured fields (human-readable and
machine-parsable). Example:

```
scope: <short scope>
changeset_strategy: <rules>
worktree_path: <path>
```

## Messages

Message beads are first-class. Use YAML frontmatter in the description and
include `thread: <bead-id>` when the message belongs to a specific epic or
changeset.

## Beads location

- If the repo already uses Beads, use that store.
- Otherwise, use the project-level Beads store as configured by Atelier.
