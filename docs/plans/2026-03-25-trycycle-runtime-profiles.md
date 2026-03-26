# Trycycle Runtime Profiles for Planner and Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Add a first-class runtime contract option to `atelier plan` and
`atelier work` so users can choose either the native Atelier contract or a
repo-owned `trycycle` contract layered on top of the existing agent CLI,
with native behavior preserved as the default.

**Architecture:** Keep runtime contract selection separate from agent
transport. Add a typed runtime-profile layer plus a shared registry, codify
the shipped `trycycle` contract inside this repo as an explicit delta from
the native planner/worker contract, and thread the selected profile into
planner and worker AGENTS/prompt generation. Validate that behavior at the
real launch boundary with end-to-end CLI scenario tests that run a recording
fixture executable through the same start-command path production uses.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pytest, existing Atelier
planner/worker runtime modules, repo-owned runtime profile docs/helpers,
subprocess-based recording test fixtures.

---

## Execution prerequisites

- Run `bash .githooks/worktree-bootstrap.sh` in this worktree before the
  first code change so repo-local hooks are bootstrapped here as required by
  `AGENTS.md`.
- Treat this plan and the repo-owned
  `docs/trycycle-runtime-contract.md` created in Task 1 as the authoritative
  shipped contract for the new runtime profile.
- Do not read `~/.codex/skills/trycycle/...` at runtime, in tests, or in the
  final implementation. Local trycycle installs were analysis input only;
  the shipped Atelier contract must live in this repo.
- Do not invent a new `ATELIER_*` environment contract for runtime profiles
  in this slice. Keep the runtime signal in config, CLI output, prompts,
  rendered `AGENTS.md`, and planner session metadata only.
- Before writing the `trycycle` profile text, read the current native
  planner and worker contract sources and record the native baseline in the
  new contract doc:
  - `src/atelier/templates/AGENTS.planner.md.tmpl`
  - `src/atelier/templates/AGENTS.worker.md.tmpl`
  - `src/atelier/commands/plan.py`
  - `src/atelier/worker/prompts.py`

## User-visible behavior

- `atelier plan` gains `--runtime native|trycycle`.
- `atelier work` gains `--runtime native|trycycle`.
- Project config gains `agent.runtime.default` plus optional
  `agent.runtime.planner` and `agent.runtime.worker` overrides.
- Runtime selection precedence is:
  CLI override, then role-scoped config override, then runtime default, then
  `native`.
- `agent.default` still selects the underlying agent CLI (`codex`,
  `claude`, etc.). Runtime selection does not replace or rename the agent
  transport.
- Native remains the default and must preserve current behavior.
- The `trycycle` runtime is an Atelier-managed profile, not a dependency on
  an external `trycycle` executable in this slice.
- Planner and worker startup output must make the chosen runtime explicit
  before the session begins.
- Planner session lookup and saved-session reuse are runtime-scoped.
  Changing planner runtime must start a fresh session instead of reusing a
  session that was created under the other runtime profile.

## Contracts and invariants

- Runtime profiles may change agent guidance, prompt construction, rendered
  `AGENTS.md` content, and planner resume namespacing. They must not change:
  Beads schema, worktree ownership, claim rules, planner sync, teardown,
  publish/finalize, or runtime environment sanitization semantics.
- The shipped `trycycle` obligations must be repo-owned. Future maintenance
  of the profile must not depend on a developer-local skill installation.
- The contract doc must record both:
  - the current native Atelier planner/worker baseline
  - the exact `trycycle` delta Atelier ships in this slice
- Resume behavior remains agent-defined. The runtime profile must not change
  how saved Codex planner session IDs are discovered or persisted when the
  runtime profile is unchanged. A runtime-profile change must intentionally
  bypass resume to avoid reviving stale planner context from the wrong
  contract.
- Planner runtime scoping must also apply when no saved session pointer
  exists. Native and trycycle planner sessions need distinct Codex session
  targets so most-recent-session fallback cannot cross runtime boundaries by
  accident.
- Do not change the shared worker/native workspace session identifier format
  in `src/atelier/workspace.py`. Runtime-specific session targeting is a
  planner concern in this slice, not a global workspace naming change.
- Worker runtime selection must not alter one-changeset-per-session behavior
  or the fail-closed startup contract.
- Planner runtime selection must not weaken the read-only planner worktree
  guardrail.
- `trycycle` is transport-agnostic in this slice. It works with the existing
  supported agents because it is a guidance profile layered over the agent
  CLI, not a new agent type.
- No migration is required. Existing configs without `agent.runtime`
  continue to resolve to `native`.
- Runtime addendum insertion must be centralized. Planner and worker should
  not each hand-build their own AGENTS block markers or block replacement
  rules.
- Even though runtime selection is contract-level rather than transport-level,
  the implementation must still be validated at the real agent-launch
  boundary with subprocess-based scenario tests. Do not rely on mocked prompt
  plumbing alone.

## Non-goals

- Do not add an external `trycycle` binary dependency or installer flow.
- Do not turn `trycycle` into a new `agents.AgentSpec`.
- Do not read developer-local skill files at runtime.
- Do not change Beads lifecycle semantics, worker publish rules, or planner
  promotion rules.
- Do not make `trycycle` the default runtime.
- Do not add new initialization prompts just to expose this feature. Runtime
  is an advanced opt-in and should be configured via CLI override or JSON
  config.

## File structure

- Create: `src/atelier/runtime_profiles/__init__.py`
  Responsibility: public runtime-profile exports and constants.
- Create: `src/atelier/runtime_profiles/models.py`
  Responsibility: typed runtime profile names and shared profile payloads.
- Create: `src/atelier/runtime_profiles/registry.py`
  Responsibility: resolve CLI/config/default precedence and return the
  selected role profile.
- Create: `src/atelier/runtime_profiles/planner.py`
  Responsibility: repo-owned planner addendum text, prompt-line helpers, and
  planner session-target helpers.
- Create: `src/atelier/runtime_profiles/worker.py`
  Responsibility: repo-owned worker addendum text and prompt-line helpers.
- Create: `docs/trycycle-runtime-contract.md`
  Responsibility: durable contract for native vs `trycycle` runtime behavior
  and the specific trycycle-derived obligations shipped in this slice.
- Create: `tests/fixtures/recording_agent.py`
  Responsibility: test-only executable that records argv/cwd/env/prompt input
  and exits deterministically.
- Create: `tests/atelier/runtime_profile_harness.py`
  Responsibility: temp-project helpers for seeding config, temp repos,
  planner/worker launch capture paths, and reading fixture artifacts.
- Create: `tests/atelier/test_runtime_profiles.py`
  Responsibility: runtime content, delta documentation, and selection
  precedence coverage.
- Create: `tests/atelier/commands/test_plan_runtime_e2e.py`
  Responsibility: CLI-level planner scenario tests using the recording agent
  fixture to prove runtime output, prompt, AGENTS content, and session
  scoping at the real launch boundary.
- Create: `tests/atelier/commands/test_work_runtime_e2e.py`
  Responsibility: CLI-level worker scenario tests using the recording agent
  fixture to prove runtime output, prompt, and AGENTS content at the real
  launch boundary.

- Modify: `src/atelier/agent_home.py`
  Responsibility: add a shared helper that inserts or replaces a
  deterministic runtime-profile addendum block in rendered `AGENTS.md`.
- Modify: `src/atelier/models.py`
  Responsibility: add typed runtime config to `AgentConfig`.
- Modify: `src/atelier/config.py`
  Responsibility: preserve runtime config through defaults and config
  rebuilds.
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
  Responsibility: extend the worker command adapter to pass runtime
  additions.
- Modify: `src/atelier/worker/session/agent.py`
  Responsibility: resolve worker runtime, apply the shared AGENTS addendum
  helper, and carry prompt additions forward to startup.
- Modify: `src/atelier/worker/session/runner.py`
  Responsibility: surface the selected worker runtime in startup output and
  use the runtime-specific prompt additions from session preparation.
- Modify: `docs/behavior.md`
  Responsibility: document config shape, CLI options, and profile semantics.
- Modify: `README.md`
  Responsibility: document the new runtime option and example usage.

- Modify tests:
  `tests/atelier/test_agent_home.py`
  `tests/atelier/test_agents.py`
  `tests/atelier/test_config.py`
  `tests/atelier/test_models.py`
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

The second wrong architecture would be to read
`~/.codex/skills/trycycle/...` from the implementation at runtime or in
tests. That would make the feature machine-local instead of repo-owned and
would make future maintenance depend on an external skill install.

The third wrong architecture would be to append trycycle text directly in
both `plan.py` and `worker/session/agent.py` with separate ad hoc block
handling. That would create two divergent AGENTS mutation paths for the same
feature.

The fourth wrong architecture would be to ship a profile named `trycycle`
without first codifying the native baseline and the exact shipped delta in
repo-owned docs and helper modules. That would turn the feature into
arbitrary prompt tweaks rather than a deliberate runtime contract.

The fifth wrong architecture would be to test this only with mocked prompt
builders and mocked launch helpers. That would miss the critical launch
boundary where CLI wiring, prompt composition, and AGENTS rendering actually
come together.

The clean steady-state design is:

- keep `agents.AgentSpec` as the CLI transport registry
- add a separate runtime-profile layer with explicit per-role resolution
- codify the native baseline and shipped `trycycle` delta inside this repo
- use a shared AGENTS addendum helper for both planner and worker
- keep native behavior encoded as the `native` profile
- implement `trycycle` as an Atelier-managed guidance profile in this slice
- validate planner and worker flows with real subprocess fixture launches
- keep Beads/worktree/finalize behavior unchanged

That solves the user’s actual goal: ship a real trycycle-like runtime option
for planner and worker phases without destabilizing the lifecycle machinery
that already exists.

### Task 1: Codify the native baseline and shipped trycycle delta

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

Before writing the contract text, read the current native planner and worker
sources listed in the prerequisites and capture the baseline sections in
`docs/trycycle-runtime-contract.md`.

Add focused tests for:

```python
def test_trycycle_contract_doc_records_native_baseline_and_delta() -> None:
    text = Path("docs/trycycle-runtime-contract.md").read_text(encoding="utf-8")
    assert "## Native Planner Baseline" in text
    assert "## Native Worker Baseline" in text
    assert "## Trycycle Delta" in text


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

Expected: FAIL because the runtime profile helpers, contract doc sections,
and shared AGENTS addendum helper do not exist.

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

Add `agent_home.apply_runtime_profile_addendum(...)` so runtime addendum
block insertion/replacement is shared and deterministic for both roles.

Write `docs/trycycle-runtime-contract.md` as the authoritative shipped
contract. It must record the current native planner/worker baseline first,
then the exact `trycycle` delta Atelier ships in this slice.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_agent_home.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Tighten naming and docstrings, keep the profile content repo-owned, and
verify the helper surface.

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
git commit -m "feat(runtime): codify repo-owned trycycle contract" \
  -m "- record the native planner and worker baseline in repo docs" \
  -m "- add repo-owned planner and worker runtime profile helpers" \
  -m "- centralize AGENTS runtime addendum insertion and cover it with tests"
```

### Task 2: Add typed runtime selection and a reusable launch-boundary harness

**Files:**
- Create: `src/atelier/runtime_profiles/registry.py`
- Create: `tests/fixtures/recording_agent.py`
- Create: `tests/atelier/runtime_profile_harness.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Modify: `src/atelier/cli.py`
- Modify: `tests/atelier/test_agents.py`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/test_models.py`
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


def test_recording_agent_fixture_captures_prompt_and_env(tmp_path: Path) -> None:
    result = run_recording_agent_fixture(tmp_path, prompt="hello")
    assert result.prompt == "hello"
    assert "PWD" in result.env
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
  tests/atelier/test_models.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: FAIL because `AgentConfig` has no runtime field, the registry does
not exist, the CLI does not pass `runtime`, and the recording fixture/harness
does not exist.

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
`build_project_config()` without adding new prompts.

Add `--runtime` to the `plan` and `work` Typer commands and pass it through
the `SimpleNamespace`.

Create the recording fixture and harness now so later planner/worker tasks can
use the same real-launch assertion surface instead of inventing separate
helpers.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/test_models.py \
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
  tests/fixtures/recording_agent.py \
  tests/atelier/runtime_profile_harness.py \
  tests/atelier/test_agents.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/test_models.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py
git commit -m "feat(runtime): add typed runtime selection" \
  -m "- add agent runtime config and precedence helpers" \
  -m "- expose runtime selection through plan and work CLI wiring" \
  -m "- add a reusable recording-agent harness for launch-boundary tests"
```

### Task 3: Integrate planner runtime profiles and prove them at the real
launch boundary

**Files:**
- Modify: `src/atelier/commands/plan.py`
- Modify: `src/atelier/runtime_profiles/planner.py`
- Modify: `src/atelier/sessions.py`
- Modify: `tests/atelier/commands/test_plan.py`
- Modify: `tests/atelier/test_sessions.py`
- Create or modify: `tests/atelier/commands/test_plan_runtime_e2e.py`
- Modify: `tests/atelier/runtime_profile_harness.py`

- [ ] **Step 1: Identify or write the failing test**

Add planner tests for:

```python
def test_plan_trycycle_runtime_appends_planner_contract_lines(...)
def test_plan_native_runtime_preserves_existing_opening_prompt(...)
def test_plan_runtime_change_starts_fresh_planner_session(...)
def test_plan_runtime_scopes_codex_session_lookup(...)
def test_plan_runtime_e2e_records_runtime_output_prompt_and_agents(...) -> None
```

The end-to-end planner scenario must:

- invoke `atelier plan --runtime trycycle`
- use the recording agent fixture through the actual start-command path
- assert startup output contains `Planner runtime: trycycle`
- assert the recorded prompt contains the trycycle planner delta
- assert the rendered `AGENTS.md` contains the runtime addendum block
- assert saved-session reuse is bypassed when the persisted runtime differs

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py \
  tests/atelier/commands/test_plan_runtime_e2e.py -v
```

Expected: FAIL because planner runtime resolution, runtime-scoped resume, and
the real-launch planner scenario do not exist.

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

In `src/atelier/sessions.py`, add either an explicit `session_target`
override to `find_codex_session(s)` or a dedicated helper that accepts a
fully-built target string. Do not change
`workspace.workspace_session_identifier(...)` globally; worker prompts and
native workspace matching must stay stable.

Use a dedicated planner session runtime field, for example:

```python
_PLANNER_SESSION_RUNTIME_FIELD = "planner_session.runtime"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py \
  tests/atelier/commands/test_plan_runtime_e2e.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Re-run the full planner command suite to prove native parity and keep the
launch-boundary scenario green.

Run:

```bash
just format
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/test_sessions.py \
  tests/atelier/commands/test_plan_runtime_e2e.py -v
```

Expected: all PASS, including the existing planner session/resume coverage.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/commands/plan.py \
  src/atelier/runtime_profiles/planner.py \
  src/atelier/sessions.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/test_sessions.py \
  tests/atelier/commands/test_plan_runtime_e2e.py \
  tests/atelier/runtime_profile_harness.py
git commit -m "feat(plan): add planner runtime profiles" \
  -m "- resolve planner runtime separately from agent transport" \
  -m "- scope planner resume to the selected runtime profile" \
  -m "- prove runtime output, prompt, and AGENTS content at the launch boundary"
```

### Task 4: Integrate worker runtime profiles and prove them at the real
launch boundary

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
- Create or modify: `tests/atelier/commands/test_work_runtime_e2e.py`
- Modify: `tests/atelier/runtime_profile_harness.py`

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


def test_work_runtime_e2e_records_runtime_output_prompt_and_agents(...) -> None:
    ...
```

The end-to-end worker scenario must:

- invoke `atelier work --runtime trycycle`
- use the recording agent fixture through the actual session start path
- assert startup output contains `Worker runtime: trycycle`
- assert the recorded prompt contains the trycycle worker delta
- assert the rendered `AGENTS.md` contains the runtime addendum block
- assert worker claim, startup-contract, and finalize behavior stay unchanged

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
  tests/atelier/commands/test_work_runtime_wiring.py \
  tests/atelier/commands/test_work_runtime_e2e.py -v
```

Expected: FAIL because the worker prompt and session prep do not accept
runtime additions, the runner does not surface runtime selection, and the
real-launch worker scenario does not exist.

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
  tests/atelier/commands/test_work_runtime_wiring.py \
  tests/atelier/commands/test_work_runtime_e2e.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Run the broader worker startup and runtime suites to prove the new profile is
additive only and keep the launch-boundary scenario green.

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
  tests/atelier/commands/test_work_runtime_wiring.py \
  tests/atelier/commands/test_work_runtime_e2e.py -v
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
  tests/atelier/commands/test_work_runtime_wiring.py \
  tests/atelier/commands/test_work_runtime_e2e.py \
  tests/atelier/runtime_profile_harness.py
git commit -m "feat(work): add worker runtime profiles" \
  -m "- thread runtime selection through worker session preparation" \
  -m "- add repo-owned trycycle worker guidance without changing lifecycle logic" \
  -m "- prove runtime output, prompt, and AGENTS content at the launch boundary"
```

### Task 5: Document the public surface, lock down parity, and land it

**Files:**
- Modify: `docs/behavior.md`
- Modify: `README.md`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/commands/test_plan_runtime_e2e.py`
- Modify: `tests/atelier/commands/test_work_runtime_e2e.py`
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
- the planner and worker end-to-end scenarios both pass in native mode and in
  trycycle mode with the expected deltas only

Use the scenario tests added earlier instead of inventing doc-only coverage
where possible.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/commands/test_plan_runtime_e2e.py \
  tests/atelier/commands/test_work_runtime_e2e.py \
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
from the high-level docs rather than duplicating the full guidance in
multiple places.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/commands/test_plan_runtime_e2e.py \
  tests/atelier/commands/test_work_runtime_e2e.py \
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
  tests/atelier/commands/test_plan_runtime_e2e.py \
  tests/atelier/commands/test_work_runtime_e2e.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py
git commit -m "docs(runtime): document trycycle runtime profiles" \
  -m "- document config and command behavior for runtime profiles" \
  -m "- lock down native-parity and role-scoped scenario coverage" \
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
- It records the native baseline before defining the shipped trycycle delta,
  so the feature is an explicit contract rather than arbitrary prompt edits.
- It centralizes AGENTS addendum handling instead of duplicating string
  mutation logic across planner and worker.
- It adds the launch-boundary scenario tests the approved testing strategy
  called for, so prompt/addendum behavior is proven where production actually
  launches agents.
- It keeps native behavior stable and testable.
