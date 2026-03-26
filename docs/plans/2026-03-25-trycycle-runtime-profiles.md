# Trycycle Runtime Profiles for Planner and Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Add a first-class runtime profile option to `atelier plan` and
`atelier work` so users can choose either the native Atelier contract or a
repo-owned `trycycle` contract layered on top of the existing agent CLI, with
native behavior preserved as the default.

**Architecture:** Keep runtime profile selection separate from agent transport.
Add a typed runtime-profile layer plus a shared registry, codify the shipped
`trycycle` contract inside this repo, and thread the selected profile into
planner and worker AGENTS/prompt generation. Use a shared AGENTS addendum
helper so planner and worker do not hand-roll separate string-splicing logic.
The selected profile may change guidance, prompt lines, and planner resume
namespacing, but it must not change Beads, worktree, claim, teardown, or
publish semantics. Keep planner runtime scoping planner-specific: add a
planner session-target helper and matching support instead of mutating the
shared workspace identifier used elsewhere.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pytest, existing Atelier
planner/worker runtime modules, repo-owned runtime profile docs/helpers.

---

## Execution prerequisites

- Run `bash .githooks/worktree-bootstrap.sh` in this worktree before the first
  code change so repo-local hooks are bootstrapped here as required by
  `AGENTS.md`.
- Treat this plan and the repo-owned
  `docs/trycycle-runtime-contract.md` created in Task 1 as the authoritative
  shipped contract for the new runtime profile.
- Do not read `~/.codex/skills/trycycle/...` at runtime, in tests, or in the
  final implementation. Local trycycle installs were analysis input only; the
  shipped Atelier contract must live in this repo.
- Do not invent a new `ATELIER_*` environment contract for runtime profiles in
  this slice. Keep the runtime signal in config, CLI output, prompts, rendered
  `AGENTS.md`, and planner session metadata only.

## User-visible behavior

- `atelier plan` gains `--runtime native|trycycle`.
- `atelier work` gains `--runtime native|trycycle`.
- Project config gains `agent.runtime.default` plus optional
  `agent.runtime.planner` and `agent.runtime.worker` overrides.
- Runtime selection precedence is:
  CLI override, then role-scoped config override, then runtime default, then
  `native`.
- `agent.default` still selects the underlying agent CLI (`codex`, `claude`,
  etc.). Runtime selection does not replace or rename the agent transport.
- Native remains the default and must preserve current behavior.
- The `trycycle` runtime is an Atelier-managed profile, not a dependency on an
  external `trycycle` executable in this slice.
- Planner and worker startup output must make the chosen runtime explicit
  before the session begins.
- Planner session lookup and saved-session reuse are runtime-scoped. Changing
  planner runtime must start a fresh session instead of reusing a session that
  was created under the other runtime profile.

## Contracts and invariants

- Runtime profiles may change agent guidance, prompt construction, rendered
  `AGENTS.md` content, and planner resume namespacing. They must not change:
  Beads schema, worktree ownership, claim rules, planner sync, teardown,
  publish/finalize, or runtime environment sanitization semantics.
- The shipped `trycycle` obligations must be repo-owned. Future maintenance of
  the profile must not depend on a developer-local skill installation.
- Resume behavior remains agent-defined. The runtime profile must not change
  how saved Codex planner session IDs are discovered or persisted when the
  runtime profile is unchanged. A runtime-profile change must intentionally
  bypass resume to avoid reviving stale planner context from the wrong
  contract.
- Planner runtime scoping must also apply when no saved session pointer exists.
  Native and trycycle planner sessions need distinct Codex session targets so
  most-recent-session fallback cannot cross runtime boundaries by accident.
- Do not change the shared worker/native workspace session identifier format in
  `src/atelier/workspace.py`. Runtime-specific session targeting is a planner
  concern in this slice, not a global workspace naming change.
- Worker runtime selection must not alter one-changeset-per-session behavior or
  the fail-closed startup contract.
- Planner runtime selection must not weaken the read-only planner worktree
  guardrail.
- `trycycle` is transport-agnostic in this slice. It works with the existing
  supported agents because it is a guidance profile layered over the agent CLI,
  not a new agent type.
- No migration is required. Existing configs without `agent.runtime` continue
  to resolve to `native`.
- Runtime addendum insertion must be centralized. Planner and worker should not
  each hand-build their own AGENTS block markers or block replacement rules.

## Non-goals

- Do not add an external `trycycle` binary dependency or installer flow.
- Do not turn `trycycle` into a new `agents.AgentSpec`.
- Do not read developer-local skill files at runtime.
- Do not change Beads lifecycle semantics, worker publish rules, or planner
  promotion rules.
- Do not make `trycycle` the default runtime.
- Do not add new initialization prompts just to expose this feature. Runtime is
  an advanced opt-in and should be configured via CLI override or JSON config.

## File structure

- Create: `src/atelier/runtime_profiles/__init__.py`
  Responsibility: public runtime-profile exports and constants.
- Create: `src/atelier/runtime_profiles/models.py`
  Responsibility: typed runtime profile names and shared profile payloads.
- Create: `src/atelier/runtime_profiles/registry.py`
  Responsibility: resolve CLI/config/default precedence and return the selected
  role profile.
- Create: `src/atelier/runtime_profiles/planner.py`
  Responsibility: repo-owned planner addendum text, prompt-line helpers, and
  planner session-target helpers.
- Create: `src/atelier/runtime_profiles/worker.py`
  Responsibility: repo-owned worker addendum text and prompt-line helpers.
- Create: `tests/atelier/test_runtime_profiles.py`
  Responsibility: runtime content and runtime selection precedence coverage.
- Create: `docs/trycycle-runtime-contract.md`
  Responsibility: durable contract for native vs `trycycle` runtime behavior
  and the specific trycycle-derived obligations shipped in this slice.

- Modify: `src/atelier/agent_home.py`
  Responsibility: add a shared helper that inserts or replaces a deterministic
  runtime-profile addendum block in rendered `AGENTS.md`.
- Modify: `src/atelier/models.py`
  Responsibility: add typed runtime config to `AgentConfig`.
- Modify: `src/atelier/config.py`
  Responsibility: preserve runtime config through defaults and config rebuilds.
- Modify: `src/atelier/cli.py`
  Responsibility: expose `--runtime` on `plan` and `work`.
- Modify: `src/atelier/commands/plan.py`
  Responsibility: resolve planner runtime, surface it to the user, apply the
  shared AGENTS addendum helper, extend the opening prompt, and keep planner
  resume scoped to the selected runtime profile.
- Modify: `src/atelier/sessions.py`
  Responsibility: allow planner runtime-specific Codex session lookup without
  changing default workspace matching behavior.
- Modify: `src/atelier/worker/ports.py`
  Responsibility: carry resolved worker runtime metadata and prompt additions
  through the worker runtime protocols.
- Modify: `src/atelier/worker/prompts.py`
  Responsibility: accept runtime-specific prompt additions without duplicating
  the base worker prompt.
- Modify: `src/atelier/worker/work_startup_runtime.py`
  Responsibility: preserve the public `worker_opening_prompt` facade while
  threading through runtime-specific prompt additions.
- Modify: `src/atelier/worker/runtime.py`
  Responsibility: extend the worker command adapter to pass runtime additions.
- Modify: `src/atelier/worker/session/agent.py`
  Responsibility: resolve worker runtime, apply the shared AGENTS addendum
  helper, and carry prompt additions forward to startup.
- Modify: `src/atelier/worker/session/runner.py`
  Responsibility: surface the selected worker runtime in startup output and use
  the runtime-specific prompt additions from session preparation.
- Modify: `docs/behavior.md`
  Responsibility: document config shape, CLI options, and profile semantics.
- Modify: `README.md`
  Responsibility: document the new runtime option and example usage.

- Modify tests:
  `tests/atelier/test_agent_home.py`
  `tests/atelier/test_agents.py`
  `tests/atelier/test_config.py`
  `tests/atelier/test_sessions.py`
  `tests/atelier/commands/test_plan_cli.py`
  `tests/atelier/commands/test_work_cli.py`
  `tests/atelier/commands/test_plan.py`
  `tests/atelier/commands/test_work_runtime_wiring.py`
  `tests/atelier/worker/test_prompts.py`
  `tests/atelier/worker/test_session_agent.py`
  `tests/atelier/worker/test_session_runner.py`
  `tests/atelier/worker/test_session_runner_flow.py`
  `tests/atelier/worker/test_runtime.py`
  `tests/atelier/worker/test_work_startup_runtime.py`
  Responsibility: cover runtime content, config defaults, CLI plumbing,
  planner/worker runtime selection, native parity, and trycycle-specific
  prompt/addendum behavior.

## Strategy gate

The wrong architecture would be to add `trycycle` as another `AgentSpec` in
`src/atelier/agents.py`. That would collapse two distinct concerns into one:
transport and runtime contract.

The second wrong architecture would be to read `~/.codex/skills/trycycle/...`
from the implementation at runtime or in tests. That would make the feature
machine-local instead of repo-owned and would make future maintenance depend on
an external skill install.

The third wrong architecture would be to append trycycle text directly in both
`plan.py` and `worker/session/agent.py` with separate ad hoc block handling.
That would create two divergent AGENTS mutation paths for the same feature.

The fourth wrong architecture would be to ship a profile named `trycycle`
without first codifying the exact shipped obligations in repo-owned docs and
helper modules. That would turn the feature into arbitrary prompt tweaks rather
than a deliberate runtime contract.

The clean steady-state design is:

- keep `agents.AgentSpec` as the CLI transport registry
- add a separate runtime-profile layer with explicit per-role resolution
- codify the shipped `trycycle` contract inside this repo first
- use a shared AGENTS addendum helper for both planner and worker
- keep native behavior encoded as the `native` profile
- implement `trycycle` as an Atelier-managed guidance profile in this slice
- keep Beads/worktree/finalize behavior unchanged

That solves the user’s actual goal: ship a real trycycle-like runtime option
for planner and worker phases without destabilizing the lifecycle machinery
that already exists.

### Task 1: Codify the shipped runtime contract inside the repo

**Files:**
- Create: `src/atelier/runtime_profiles/__init__.py`
- Create: `src/atelier/runtime_profiles/models.py`
- Create: `src/atelier/runtime_profiles/planner.py`
- Create: `src/atelier/runtime_profiles/worker.py`
- Create: `tests/atelier/test_runtime_profiles.py`
- Create: `docs/trycycle-runtime-contract.md`
- Modify: `src/atelier/agent_home.py`
- Modify: `tests/atelier/test_agent_home.py`

- [ ] **Step 1: Identify or write the failing test**

Add focused tests for:

```python
def test_planner_trycycle_runtime_returns_repo_owned_addendum() -> None:
    addendum = planner_runtime_addendum("trycycle")
    assert "Diagnose the plan completely before deciding anything." in addendum


def test_worker_trycycle_runtime_returns_repo_owned_prompt_lines() -> None:
    lines = worker_runtime_prompt_lines("trycycle")
    assert "Execute the work task-by-task." in lines


def test_apply_runtime_profile_addendum_inserts_named_block() -> None:
    updated = agent_home.apply_runtime_profile_addendum(
        "# Base\n",
        "extra guidance",
        role="planner",
        runtime_name="trycycle",
    )
    assert "## Runtime Profile Addendum" in updated
    assert "Runtime: trycycle" in updated
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_agent_home.py -k runtime -v
```

Expected: FAIL because the runtime profile helpers and shared AGENTS addendum
helper do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement the repo-owned contract helpers first:

```python
RuntimeProfileName = Literal["native", "trycycle"]


def planner_runtime_addendum(runtime_name: RuntimeProfileName) -> str:
    if runtime_name == "native":
        return ""
    return "\n".join(
        [
            "## Runtime Profile: trycycle",
            "- Diagnose the plan completely before deciding anything.",
            "- Capture behavior, invariants, and failure modes before task breakdown.",
            "- Make architecture decisions before decomposition.",
        ]
    )
```

```python
def worker_runtime_prompt_lines(
    runtime_name: RuntimeProfileName,
) -> tuple[str, ...]:
    if runtime_name == "native":
        return ()
    return (
        "Restate the bead contract as a concrete checklist before coding.",
        "Execute the work task-by-task.",
        "Do not skip required repo gates, push, or publish steps.",
    )
```

Add `agent_home.apply_runtime_profile_addendum(...)` so runtime addendum block
insertion/replacement is shared and deterministic for both roles.

Write `docs/trycycle-runtime-contract.md` as the authoritative shipped
contract. It should capture the exact planner and worker obligations Atelier
ships in this slice and state explicitly that runtime profiles change guidance
only, not lifecycle semantics.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_agent_home.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Tighten naming and docstrings, keep the profile content repo-owned, and verify
the helper surface.

Run:

```bash
just format
uv run pytest \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_agent_home.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/runtime_profiles/__init__.py \
  src/atelier/runtime_profiles/models.py \
  src/atelier/runtime_profiles/planner.py \
  src/atelier/runtime_profiles/worker.py \
  src/atelier/agent_home.py \
  docs/trycycle-runtime-contract.md \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_agent_home.py
git commit -m "feat(runtime): codify repo-owned trycycle profile contract" \
  -m "- add repo-owned planner and worker runtime profile helpers" \
  -m "- centralize AGENTS runtime addendum insertion" \
  -m "- document the shipped trycycle contract and cover it with tests"
```

### Task 2: Add typed runtime-profile selection to config and CLI

**Files:**
- Create: `src/atelier/runtime_profiles/registry.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Modify: `src/atelier/cli.py`
- Modify: `tests/atelier/test_agents.py`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/commands/test_plan_cli.py`
- Modify: `tests/atelier/commands/test_work_cli.py`
- Modify: `tests/atelier/test_runtime_profiles.py`

- [ ] **Step 1: Identify or write the failing test**

Add focused tests for:

```python
def test_agent_runtime_config_defaults_to_native() -> None:
    config = AgentConfig(default="codex")
    assert config.runtime.default == "native"
    assert config.runtime.planner is None
    assert config.runtime.worker is None


def test_runtime_selection_precedence_cli_over_role_over_default() -> None:
    runtime = registry.resolve_runtime_name(
        role="worker",
        cli_override="trycycle",
        runtime_config=AgentRuntimeConfig(default="native", worker="native"),
    )
    assert runtime == "trycycle"
```

Extend the CLI tests so `plan` and `work` must pass a `runtime` attribute
through to the command layer.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: FAIL because `AgentConfig` has no runtime field, the registry does
not exist, and the CLI does not pass `runtime`.

- [ ] **Step 3: Write minimal implementation**

Add a typed runtime config that stays separate from the agent transport:

```python
class AgentRuntimeConfig(BaseModel):
    default: RuntimeProfileName = "native"
    planner: RuntimeProfileName | None = None
    worker: RuntimeProfileName | None = None
```

Add registry helpers with explicit precedence:

```python
def resolve_runtime_name(
    *,
    role: str,
    cli_override: str | None,
    runtime_config: AgentRuntimeConfig | None,
) -> RuntimeProfileName:
    if cli_override is not None:
        return normalize_runtime_name(cli_override, source="--runtime")
    if runtime_config is not None:
        role_value = getattr(runtime_config, normalize_launch_role(role), None)
        if role_value:
            return role_value
        return runtime_config.default
    return "native"
```

Thread the new field through `AgentConfig`, `default_user_config()`, and
`build_project_config()` without adding new prompts. Add `--runtime` to the
`plan` and `work` Typer commands and pass it through the `SimpleNamespace`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Tighten naming and docstrings, keep the runtime helpers out of
`src/atelier/agents.py`, and verify the broader config/model surface.

Run:

```bash
just format
uv run pytest \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/test_models.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/runtime_profiles/registry.py \
  src/atelier/models.py \
  src/atelier/config.py \
  src/atelier/cli.py \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py
git commit -m "feat(runtime): add typed runtime profile selection" \
  -m "- add agent runtime config and precedence helpers" \
  -m "- expose runtime selection through plan and work CLI wiring" \
  -m "- cover defaults and CLI plumbing with tests"
```

### Task 3: Integrate planner runtime profiles without changing planner safety

**Files:**
- Modify: `src/atelier/commands/plan.py`
- Modify: `src/atelier/runtime_profiles/planner.py`
- Modify: `src/atelier/sessions.py`
- Modify: `tests/atelier/commands/test_plan.py`
- Modify: `tests/atelier/test_sessions.py`

- [ ] **Step 1: Identify or write the failing test**

Add planner tests for:

```python
def test_plan_trycycle_runtime_appends_planner_contract_lines(...)
def test_plan_native_runtime_preserves_existing_opening_prompt(...)
def test_plan_runtime_change_starts_fresh_planner_session(...)
def test_plan_runtime_scopes_codex_session_lookup(...)
def test_find_codex_sessions_accepts_runtime_scoped_planner_target(...) -> None
```

The trycycle planner contract should require:

- explicit diagnosis of behavior, invariants, and failure modes before changeset
  decomposition
- architecture decisions before task breakdown
- no weakening of planner read-only, sync, or teardown rules

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py -k runtime -v
```

Expected: FAIL because planner runtime resolution and runtime-scoped resume do
not exist.

- [ ] **Step 3: Write minimal implementation**

In `run_planner(...)`:

- resolve the planner runtime via the registry
- print `Planner runtime: <name>`
- compute a planner-specific session target from the selected runtime
- apply the shared runtime addendum helper to rendered planner `AGENTS.md`
- extend `_planner_opening_prompt(...)` to accept runtime-specific lines
- persist both planner session id and planner runtime when Codex returns a
  session id
- if the saved planner runtime differs from the selected runtime, bypass
  resume, clear the stale saved session pointer, and start a fresh session
  under the selected runtime target
- keep resume/session-id logic, sync monitor, guardrails, and teardown
  otherwise unchanged

In `src/atelier/runtime_profiles/planner.py`, add a helper that derives the
planner session target from the existing workspace identifier plus the runtime
name, for example by appending a deterministic runtime suffix for non-native
planner sessions.

In `src/atelier/sessions.py`, add either an explicit `session_target` override
to `find_codex_session(s)` or a dedicated helper that accepts a fully-built
target string. Do not change `workspace.workspace_session_identifier(...)`
globally; worker prompts and native workspace matching must stay stable.

Use a dedicated planner session runtime field, for example:

```python
_PLANNER_SESSION_RUNTIME_FIELD = "planner_session.runtime"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Re-run the full planner command suite to prove native parity.

Run:

```bash
just format
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/test_sessions.py -v
```

Expected: all PASS, including the existing planner session/resume coverage.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/commands/plan.py \
  src/atelier/runtime_profiles/planner.py \
  src/atelier/sessions.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py
git commit -m "feat(plan): add planner runtime profiles" \
  -m "- resolve planner runtime separately from agent transport" \
  -m "- scope planner resume to the selected runtime profile" \
  -m "- apply repo-owned planner runtime guidance to prompts and AGENTS output"
```

### Task 4: Integrate worker runtime profiles without changing worker lifecycle

**Files:**
- Modify: `src/atelier/worker/ports.py`
- Modify: `src/atelier/worker/prompts.py`
- Modify: `src/atelier/worker/work_startup_runtime.py`
- Modify: `src/atelier/worker/runtime.py`
- Modify: `src/atelier/worker/session/agent.py`
- Modify: `src/atelier/worker/session/runner.py`
- Modify: `src/atelier/runtime_profiles/worker.py`
- Modify: `tests/atelier/worker/test_prompts.py`
- Modify: `tests/atelier/worker/test_session_agent.py`
- Modify: `tests/atelier/worker/test_session_runner.py`
- Modify: `tests/atelier/worker/test_session_runner_flow.py`
- Modify: `tests/atelier/worker/test_runtime.py`
- Modify: `tests/atelier/worker/test_work_startup_runtime.py`
- Modify: `tests/atelier/commands/test_work_runtime_wiring.py`

- [ ] **Step 1: Identify or write the failing test**

Add worker-facing tests for:

```python
def test_worker_opening_prompt_includes_trycycle_contract_lines() -> None:
    prompt = worker_opening_prompt(..., runtime_lines=("Execute the work task-by-task.",))
    assert "Execute the work task-by-task." in prompt


def test_prepare_agent_session_applies_trycycle_worker_addendum(...) -> None:
    ...


def test_work_runtime_wiring_passes_runtime_override_to_worker_session(...) -> None:
    ...


def test_worker_session_runner_reports_selected_runtime(...) -> None:
    ...


def test_work_startup_runtime_facade_accepts_runtime_prompt_lines(...) -> None:
    ...
```

The trycycle worker contract should require:

- derive a concrete checklist from the seeded bead before coding
- execute the work task-by-task instead of broad free-form execution
- keep all existing finalize, push, publish, and fail-closed semantics

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/worker/test_runtime.py \
  tests/atelier/worker/test_work_startup_runtime.py \
  tests/atelier/commands/test_work_runtime_wiring.py -k runtime -v
```

Expected: FAIL because the worker prompt and session prep do not accept runtime
additions and the runner does not surface runtime selection.

- [ ] **Step 3: Write minimal implementation**

Then:

- resolve the worker runtime once in session preparation
- carry the resolved runtime name and prompt additions in
  `AgentSessionPreparation`
- extend the worker command/service protocols so runner code can receive the
  runtime-specific prompt additions without ad hoc attribute access
- apply the shared runtime addendum helper to rendered worker `AGENTS.md`
- extend `worker_opening_prompt(...)` to accept additive runtime lines
- surface `Worker runtime: <name>` in startup output before the agent session
  begins
- keep startup selection, claim logic, worktree preparation, and finalize
  behavior unchanged

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/worker/test_runtime.py \
  tests/atelier/worker/test_work_startup_runtime.py \
  tests/atelier/commands/test_work_runtime_wiring.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Run the broader worker startup and runtime suites to prove the new profile is
additive only.

Run:

```bash
just format
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/worker/test_runtime.py \
  tests/atelier/worker/test_work_startup_runtime.py \
  tests/atelier/commands/test_work.py \
  tests/atelier/commands/test_work_cli.py \
  tests/atelier/commands/test_work_runtime_wiring.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/worker/ports.py \
  src/atelier/worker/prompts.py \
  src/atelier/worker/work_startup_runtime.py \
  src/atelier/worker/runtime.py \
  src/atelier/worker/session/agent.py \
  src/atelier/worker/session/runner.py \
  src/atelier/runtime_profiles/worker.py \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/worker/test_runtime.py \
  tests/atelier/worker/test_work_startup_runtime.py \
  tests/atelier/commands/test_work_runtime_wiring.py
git commit -m "feat(work): add worker runtime profiles" \
  -m "- thread runtime selection through worker session preparation" \
  -m "- add repo-owned trycycle worker guidance without changing lifecycle logic" \
  -m "- surface the selected worker runtime in startup output"
```

### Task 5: Document the public surface, lock down parity, and land it

**Files:**
- Modify: `docs/behavior.md`
- Modify: `README.md`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/commands/test_plan.py`
- Modify: `tests/atelier/worker/test_session_agent.py`
- Modify: `tests/atelier/worker/test_session_runner.py`

- [ ] **Step 1: Identify or write the failing test**

Add or extend tests that prove the intended end-state contract:

- config without `agent.runtime` still behaves as native
- planner native runtime keeps the existing prompt wording
- worker native runtime keeps the existing prompt wording
- trycycle runtime is additive and role-scoped
- planner runtime changes do not resume a session created under the other
  runtime profile

Use existing tests instead of inventing doc-only coverage where possible.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py -k "runtime or native" -v
```

Expected: FAIL until the native-parity and role-scoped assertions exist and
pass.

- [ ] **Step 3: Write minimal implementation**

Document the behavior explicitly:

- `docs/behavior.md`
  Add the new config shape and `--runtime` command behavior.
- `README.md`
  Add one short example for planner and worker usage:

```bash
atelier plan --runtime trycycle
atelier work --runtime trycycle
```

Keep `docs/trycycle-runtime-contract.md` as the deep contract and reference it
from the high-level docs rather than duplicating the full guidance in multiple
places.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py -k "runtime or native" -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Run the repo-required gates for the completed slice on the final formatted
state.

Run:

```bash
just test
just format
just test
just lint
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/behavior.md \
  README.md \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py
git commit -m "docs(runtime): document trycycle runtime profiles" \
  -m "- document config and command behavior for runtime profiles" \
  -m "- lock down native-parity and role-scoped regression coverage" \
  -m "- reference the repo-owned runtime contract from user-facing docs"
```

## Final verification and landing

- [ ] If any follow-up work remains, create linked `bd` issues for it before
  ending the session. If nothing remains, explicitly note that no follow-up
  issues were required.
- [ ] Run:

```bash
git status --short
git pull --rebase
git push
git status
```

Expected:

- quality gates already passed
- branch pushes cleanly
- final `git status` shows the branch is up to date with `origin`

- [ ] Clean up any stale local session residue that this slice created and
  verify there are no leftover stashes before handing off.

## Why this plan is the right cutover

- It lands the full feature directly: a real per-role runtime option with a
  shipped `trycycle` profile.
- It avoids the main design mistake of conflating runtime behavior with agent
  transport.
- It removes the biggest execution risk in the prior draft: dependence on a
  developer-local trycycle install as the source of truth for shipped behavior.
- It centralizes AGENTS addendum handling instead of duplicating string
  mutation logic across planner and worker.
- It keeps native behavior stable and testable.
