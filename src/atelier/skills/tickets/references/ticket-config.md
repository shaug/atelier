# Ticket association config

## Config locations

- Workspace ticket references live in `<workspace>/config.user.json` under
  `tickets.refs`.
- Project ticket defaults live in `<project>/config.user.json` under
  `tickets.provider`, `tickets.default_project`, and
  `tickets.default_namespace`.
- `config.sys.json` is system-managed; do not write ticket refs there.

## Schema snippets

Workspace config (user-managed):

```json
{
  "tickets": {
    "refs": [
      "GH-123",
      "OPS-9"
    ]
  }
}
```

Project config (user-managed):

```json
{
  "tickets": {
    "provider": "github",
    "default_project": "org/repo",
    "default_namespace": "org"
  }
}
```

## Association rules (provider-agnostic)

- Treat `tickets.refs` as the source of truth for workspace ticket attachment.
- Preserve existing order and append new refs; dedupe case-insensitively.
- Store refs exactly as provided after trimming; do not rewrite
  provider-specific IDs or URLs.
- Only update the workspace referenced by the user-supplied branch or workspace
  root path.

## Provider routing

- When `tickets.provider` is `github`, delegate ticket metadata reads/updates to
  the `github-issues` skill using `default_project` as the fallback repo.
- When `tickets.provider` is `linear`, delegate to the `linear` skill.
- When `tickets.provider` is `none`, skip external ticket operations and only
  update local refs.
