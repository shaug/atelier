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

| Variable | Owner (set path) | Primary consumers | Class | | --- | --- | --- |
--- | | `ATELIER_AGENT_ID` | `src/atelier/agents.py::agent_environment` |
`src/atelier/agent_home.py`, `src/atelier/beads.py`,
`src/atelier/planner_sync.py`, `src/atelier/worker/work_finalization_state.py`,
`src/atelier/skills/planner-startup-check/scripts/refresh_overview.py` | session
identity | | `ATELIER_WORKSPACE` |
`src/atelier/workspace.py::workspace_environment` | downstream shell/editor
commands launched by `atelier open` / `atelier edit` | workspace context | |
`ATELIER_PROJECT` | `src/atelier/workspace.py::workspace_environment` |
`src/atelier/beads_context.py::resolve_runtime_repo_dir_hint` (legacy fallback),
`src/atelier/auto_export.py::resolve_auto_export_context` (indirect via beads
context helper) | project routing | | `ATELIER_WORKSPACE_DIR` |
`src/atelier/workspace.py::workspace_environment` |
`src/atelier/beads_context.py::resolve_runtime_repo_dir_hint` | project routing
| | `ATELIER_HOOKS_PATH` | `src/atelier/hooks.py::ensure_hooks_path` |
hook-capable runtimes (Claude/Gemini/OpenCode/Copilot) | hook handoff | |
`ATELIER_EPIC_ID` | `src/atelier/worker/session/agent.py::prepare_agent_session`
| `src/atelier/commands/hook.py` | hook/session context | |
`ATELIER_CHANGESET_ID` |
`src/atelier/worker/session/agent.py::prepare_agent_session` |
`src/atelier/commands/hook.py` | hook/session context | | `ATELIER_PLAN_EPIC` |
`src/atelier/commands/plan.py::run_planner` | planner-agent skill flows and
prompts | planner context | | `ATELIER_BEADS_PREFIX` |
`src/atelier/commands/plan.py::run_planner`,
`src/atelier/worker/session/agent.py::prepare_agent_session` |
`src/atelier/beads.py` runtime label/prefix resolution | beads routing | |
`ATELIER_EXTERNAL_PROVIDERS` |
`src/atelier/external_registry.py::planner_provider_environment` |
`src/atelier/skills/tickets/SKILL.md` workflows | provider routing | |
`ATELIER_EXTERNAL_PROVIDER` |
`src/atelier/external_registry.py::planner_provider_environment` |
skills/provider selection flows | provider routing | |
`ATELIER_EXTERNAL_AUTO_EXPORT` |
`src/atelier/external_registry.py::planner_provider_environment` | external
export behavior hints for runtime scripts | provider routing | |
`ATELIER_GITHUB_REPO` |
`src/atelier/external_registry.py::planner_provider_environment` |
`src/atelier/skills/tickets/SKILL.md` workflows | provider routing | |
`ATELIER_PLANNER_SYNC_ENABLED` |
`src/atelier/planner_sync.py::runtime_environment` |
`src/atelier/planner_sync.py::maybe_sync_from_hook` | planner sync routing | |
`ATELIER_AGENT_BEAD_ID` | `src/atelier/planner_sync.py::runtime_environment` |
`src/atelier/planner_sync.py::maybe_sync_from_hook`, `src/atelier/beads.py` |
planner sync routing | | `ATELIER_PLANNER_WORKTREE` |
`src/atelier/planner_sync.py::runtime_environment` |
`src/atelier/planner_sync.py::maybe_sync_from_hook` | planner sync routing | |
`ATELIER_PLANNER_BRANCH` | `src/atelier/planner_sync.py::runtime_environment` |
`src/atelier/planner_sync.py::maybe_sync_from_hook` | planner sync routing | |
`ATELIER_DEFAULT_BRANCH` | `src/atelier/planner_sync.py::runtime_environment` |
`src/atelier/planner_sync.py::maybe_sync_from_hook` | planner sync routing |
