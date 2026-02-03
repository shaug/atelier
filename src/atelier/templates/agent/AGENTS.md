# AGENTS.md (Agent Home)

This directory is the persistent home for a single agent identity.

## Identity

- Set `ATELIER_AGENT_ID` to a stable identity (e.g. `atelier/worker/alice`).
- This directory name should match the human-readable identity segment.

## Startup Contract

- Check for an existing hook before starting new work.
- If no hook is present, check for message beads before claiming work.

## Hooks (If Supported)

- Hook-capable runtimes (Claude, Gemini, OpenCode) can use Atelier hook configs.
- `ATELIER_HOOKS_PATH` points to the generated hook config in this agent home.
- If your runtime cannot load hooks, follow the Startup Contract manually.

## Notes

- Project policy (if configured) is injected below for this agent role.
- Use this file for durable agent behavior and identity guidelines.
