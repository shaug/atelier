# AGENTS.md (Agent Home)

This directory is the persistent home for a single agent identity.

## Identity

- Set `ATELIER_AGENT_ID` to a stable identity (e.g. `atelier/worker/alice`).
- This directory name should match the human-readable identity segment.

## Startup Contract

- Check for an existing hook before starting new work.
- If no hook is present, check for message beads before claiming work.

## Notes

- Do not store repo-specific instructions here.
- Use this file for durable agent behavior and identity only.
