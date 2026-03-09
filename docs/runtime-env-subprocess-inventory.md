# Runtime `ATELIER_*` Subprocess Inventory

This inventory documents every `ATELIER_*` variable currently written by Atelier
when launching planner/worker/editor/shell subprocesses.

## Runtime launch policy

- Subprocess launch env is sanitized by
  `src/atelier/runtime_env.py::sanitize_subprocess_environment`.
- Inherited routing keys from ambient parent env are ignored.
- Internal launch flows no longer use ambient fallback routing via
  `ATELIER_PROJECT`, `ATELIER_WORKSPACE_DIR`, or cross-session
  `ATELIER_AGENT_ID`.

## Operator migration notes

- Scripts that need repository resolution must pass `--repo-dir` explicitly or
  run from an agent home that has a local `./worktree` link.
- Planner startup refresh commands should pass `--agent-id` explicitly instead
  of relying on inherited shell state.
- The `refresh_overview.py` failure after `at-g5a19` was an uncovered
  interpreter-selection mode, not another source-path-ordering regression:
  projected planner scripts could still start under an incompatible ambient
  `python3` / installed-tool runtime and then import repo source against those
  installed dependencies.
- That boundary is now explicit in planner helper diagnostics: repo-source
  bootstrap bugs and installed-tool dependency-health failures are treated as
  separate classes. Helpers fail closed before import-time crashes when the
  selected interpreter cannot import `pydantic_core._pydantic_core`.
- The recurring cross-project drift after `at-g5a19`, `at-34t6h`, and
  `at-s6qu4` was that projected helper entrypoints were still using multiple
  bootstrap contracts. Some scripts re-execed into the repo runtime, while
  others still imported `atelier` directly or only reordered `sys.path`.
  Projected skill scripts that import `atelier` now share
  `src/atelier/skills/shared/scripts/projected_bootstrap.py`, so repo-source
  selection, runtime re-exec, and dependency-health diagnostics stay in
  lockstep for every helper entrypoint instead of drifting one script at a
  time.
- Runtime warnings about removed inherited keys are now immediate guidance for
  explicit launch context, not future deprecation notices.

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
  - Primary consumers: downstream shell/editor commands and user scripts that
    run inside workspace-aware subprocesses.
  - Class: workspace context
- `ATELIER_WORKSPACE_DIR`
  - Owner (set path): `src/atelier/workspace.py::workspace_environment`
  - Primary consumers: downstream shell/editor commands and user scripts that
    run inside workspace-aware subprocesses.
  - Class: workspace context
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
