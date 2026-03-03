# Runtime `ATELIER_*` Subprocess Inventory

This inventory documents every `ATELIER_*` variable currently written by Atelier
when launching planner/worker/editor/shell subprocesses.

## Runtime launch policy

- Subprocess launch env is sanitized by
  `src/atelier/runtime_env.py::sanitize_subprocess_environment`.
- Inherited routing keys from ambient parent env are ignored.
- Legacy ambient fallback compatibility is scheduled for removal after
  `2026-07-01`.

## Variable inventory

- `ATELIER_AGENT_ID`
  - Owner (set path): `src/atelier/agents.py::agent_environment`
  - Primary consumers: `src/atelier/agent_home.py`, `src/atelier/beads.py`,
    `src/atelier/planner_sync.py`,
    `src/atelier/worker/work_finalization_state.py`,
    `src/atelier/skills/planner-startup-check/scripts/refresh_overview.py`
  - Class: session identity
- `ATELIER_WORKSPACE`
  - Owner (set path): `src/atelier/workspace.py::workspace_environment`
  - Primary consumers: downstream shell/editor commands launched by
    `atelier open` / `atelier edit`
  - Class: workspace context
- `ATELIER_PROJECT`
  - Owner (set path): `src/atelier/workspace.py::workspace_environment`
  - Primary consumers:
    `src/atelier/beads_context.py::resolve_runtime_repo_dir_hint` (legacy
    fallback), `src/atelier/auto_export.py::resolve_auto_export_context`
    (indirect via beads context helper)
  - Class: project routing
- `ATELIER_WORKSPACE_DIR`
  - Owner (set path): `src/atelier/workspace.py::workspace_environment`
  - Primary consumers:
    `src/atelier/beads_context.py::resolve_runtime_repo_dir_hint`
  - Class: project routing
- `ATELIER_HOOKS_PATH`
  - Owner (set path): `src/atelier/hooks.py::ensure_hooks_path`
  - Primary consumers: hook-capable runtimes (Claude/Gemini/OpenCode/Copilot)
  - Class: hook handoff
- `ATELIER_EPIC_ID`
  - Owner (set path):
    `src/atelier/worker/session/agent.py::prepare_agent_session`
  - Primary consumers: `src/atelier/commands/hook.py`
  - Class: hook/session context
- `ATELIER_CHANGESET_ID`
  - Owner (set path):
    `src/atelier/worker/session/agent.py::prepare_agent_session`
  - Primary consumers: `src/atelier/commands/hook.py`
  - Class: hook/session context
- `ATELIER_PLAN_EPIC`
  - Owner (set path): `src/atelier/commands/plan.py::run_planner`
  - Primary consumers: planner-agent skill flows and prompts
  - Class: planner context
- `ATELIER_BEADS_PREFIX`
  - Owner (set path): `src/atelier/commands/plan.py::run_planner`,
    `src/atelier/worker/session/agent.py::prepare_agent_session`
  - Primary consumers: `src/atelier/beads.py` runtime label/prefix resolution
  - Class: beads routing
- `ATELIER_EXTERNAL_PROVIDERS`
  - Owner (set path):
    `src/atelier/external_registry.py::planner_provider_environment`
  - Primary consumers: `src/atelier/skills/tickets/SKILL.md` workflows
  - Class: provider routing
- `ATELIER_EXTERNAL_PROVIDER`
  - Owner (set path):
    `src/atelier/external_registry.py::planner_provider_environment`
  - Primary consumers: skills/provider selection flows
  - Class: provider routing
- `ATELIER_EXTERNAL_AUTO_EXPORT`
  - Owner (set path):
    `src/atelier/external_registry.py::planner_provider_environment`
  - Primary consumers: external export behavior hints for runtime scripts
  - Class: provider routing
- `ATELIER_GITHUB_REPO`
  - Owner (set path):
    `src/atelier/external_registry.py::planner_provider_environment`
  - Primary consumers: `src/atelier/skills/tickets/SKILL.md` workflows
  - Class: provider routing
- `ATELIER_PLANNER_SYNC_ENABLED`
  - Owner (set path): `src/atelier/planner_sync.py::runtime_environment`
  - Primary consumers: `src/atelier/planner_sync.py::maybe_sync_from_hook`
  - Class: planner sync routing
- `ATELIER_AGENT_BEAD_ID`
  - Owner (set path): `src/atelier/planner_sync.py::runtime_environment`
  - Primary consumers: `src/atelier/planner_sync.py::maybe_sync_from_hook`,
    `src/atelier/beads.py`
  - Class: planner sync routing
- `ATELIER_PLANNER_WORKTREE`
  - Owner (set path): `src/atelier/planner_sync.py::runtime_environment`
  - Primary consumers: `src/atelier/planner_sync.py::maybe_sync_from_hook`
  - Class: planner sync routing
- `ATELIER_PLANNER_BRANCH`
  - Owner (set path): `src/atelier/planner_sync.py::runtime_environment`
  - Primary consumers: `src/atelier/planner_sync.py::maybe_sync_from_hook`
  - Class: planner sync routing
- `ATELIER_DEFAULT_BRANCH`
  - Owner (set path): `src/atelier/planner_sync.py::runtime_environment`
  - Primary consumers: `src/atelier/planner_sync.py::maybe_sync_from_hook`
  - Class: planner sync routing
