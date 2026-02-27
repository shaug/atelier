# Beads conventions (Atelier)

Use these conventions when creating or updating Beads in Atelier-managed
projects. Stick to core Beads fields so existing Beads repos remain compatible.

## Labels

- `at:epic` for workspace epics. This is required identity/index metadata for
  epic discovery queries (`bd list --label at:epic`).
- `at:hooked` for epics claimed by an agent
- `at:message` for message beads
- `at:unread` for unread message beads
- `at:policy` for project-wide agent policy

## Status

- Prefer Beads core statuses plus planning status (`deferred`, `open`,
  `in_progress`, `blocked`, `closed`).
- Use `deferred` for planned/draft work and `open` for executable work.
- Promotion is a status transition (`deferred -> open`), not a lifecycle-label
  mutation.
- Lifecycle authority is canonical status + graph semantics; labels are not
  execution gates. `cs:*` lifecycle labels are not execution gates. `cs:merged`
  and `cs:abandoned` are used on closed changeset beads to indicate
  resolution/integration status.
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
external_tickets: <json list>
```

Agent hook storage:

- Store the active hook in the agent bead slot
  (`bd slot set <agent> hook <epic>`).
- Keep `hook_bead` in the description only as a legacy fallback/backfill field.

## Messages

Message beads are first-class. Use YAML frontmatter in the description and
include `thread: <bead-id>` when the message belongs to a specific epic or
changeset.

Queue/channel frontmatter fields (optional):

- `queue`: queue name (for work intake)
- `claimed_by` / `claimed_at`: queue claim metadata
- `channel`: channel name
- `retention_days` or `expires_at`: explicit retention policy for channel posts

## Beads location

- If the repo already uses Beads, use that store.
- Otherwise, use the project-level Beads store as configured by Atelier.
