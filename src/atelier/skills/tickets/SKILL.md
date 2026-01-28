---
name: tickets
description: >-
  Associate Atelier workspaces with ticket references and route provider-specific
  ticket operations. Use when a user asks to attach ticket IDs or URLs to a
  workspace branch, list or edit workspace ticket refs, or coordinate ticket
  metadata updates via a provider skill (GitHub issues or Linear).
---

# Manage workspace tickets

## Inputs

- workspace_branch: workspace branch name or workspace root path to target.
- ticket_provider: `none`, `github`, or `linear` (from project config or user).
- ticket_refs: one or more ticket IDs or URLs to attach.
- default_project: optional default project (for GitHub, `OWNER/REPO`).
- default_namespace: optional namespace for providers that need it.

## Steps

1. Confirm the target workspace branch/root and the ticket provider.
1. Load association rules and config locations from
   [references/ticket-config.md](references/ticket-config.md).
1. Attach refs to the workspace config by running:
   `scripts/attach_ticket_refs.py --workspace <workspace_root> --ref <ticket-ref> [--ref <ticket-ref> ...]`.
1. Read existing refs from `<workspace_root>/config.user.json` at `tickets.refs`
   when the user asks to list or verify attachments.
1. Delegate provider-specific ticket operations:
   - For `github`, use the `github-issues` skill with `default_project` as the
     fallback repo.
   - For `linear`, use the `linear` skill.
   - For `none`, skip external operations and report that only local refs were
     updated.
