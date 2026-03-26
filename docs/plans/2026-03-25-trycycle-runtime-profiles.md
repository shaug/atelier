# Trycycle Runtime Profiles for Planner and Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Add a first-class runtime profile option to `atelier plan` and
`atelier work` so users can choose either the native Atelier session contract
or a trycycle-style contract on top of the existing agent CLI, with native
behavior preserved as the default.

**Architecture:** Introduce typed runtime-profile configuration and a shared
runtime registry that is distinct from `agent.default`, then thread the
selected profile into planner and worker launch preparation. Native remains the
zero-behavior-change profile; the new `trycycle` profile adds role-specific
prompt and `AGENTS.md` addenda that impose trycycle-like planning and execution
discipline without changing Beads, worktree, claim, teardown, or publish
semantics.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pytest, existing Atelier
planner/worker runtime modules.

---

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
- Planner and worker startup output should make the chosen runtime explicit so
  the user can see what contract is active before the session begins.

## Contracts and invariants

- Runtime profiles may change agent guidance, prompt construction, and rendered
  `AGENTS.md` content. They must not change:
  Beads schema, worktree ownership, claim rules, planner sync, teardown,
  publish/finalize, or runtime-env sanitization semantics.
- Resume behavior remains agent-defined. The runtime profile must not change
  how saved Codex planner session IDs are discovered or persisted.
- Worker runtime selection must not alter one-changeset-per-session behavior or
  the fail-closed startup contract.
- Planner runtime selection must not weaken the read-only planner worktree
  guardrail.
- `trycycle` is transport-agnostic in this slice. It works with the existing
  supported agents because it is a guidance profile layered over the agent CLI,
  not a new agent type.
- No migration is required. Existing configs without `agent.runtime` continue
  to resolve to `native`.

## Non-goals

- Do not add an external `trycycle` binary dependency or installer flow.
- Do not turn `trycycle` into a new `agents.AgentSpec`.
- Do not change Beads lifecycle semantics, worker publish rules, or planner
  promotion rules.
- Do not make `trycycle` the default runtime.
- Do not add new initialization prompts just to expose this feature. Runtime is
  an advanced opt-in and should be configured via CLI override or JSON config.

## File structure

- Create: `src/atelier/runtime_profiles/__init__.py`
  Responsibility: public runtime-profile exports and constants.
- Create: `src/atelier/runtime_profiles/models.py`
  Responsibility: typed runtime profile names, config models, and selection
  payloads.
- Create: `src/atelier/runtime_profiles/registry.py`
  Responsibility: resolve CLI/config/default precedence and return the selected
  role profile.
- Create: `src/atelier/runtime_profiles/planner.py`
  Responsibility: runtime-specific planner prompt lines and planner
  `AGENTS.md` addenda.
- Create: `src/atelier/runtime_profiles/worker.py`
  Responsibility: runtime-specific worker prompt lines and worker
  `AGENTS.md` addenda.
- Create: `tests/atelier/test_runtime_profiles.py`
  Responsibility: config parsing and runtime selection precedence coverage.
- Create: `docs/trycycle-runtime-contract.md`
  Responsibility: durable contract for native vs `trycycle` runtime behavior.

- Modify: `src/atelier/models.py`
  Responsibility: add typed runtime config to `AgentConfig`.
- Modify: `src/atelier/config.py`
  Responsibility: preserve runtime config through defaults and config rebuilds.
- Modify: `src/atelier/cli.py`
  Responsibility: expose `--runtime` on `plan` and `work`.
- Modify: `src/atelier/commands/plan.py`
  Responsibility: resolve planner runtime, surface it to the user, append
  planner runtime addendum to rendered `AGENTS.md`, and augment the opening
  prompt.
- Modify: `src/atelier/worker/prompts.py`
  Responsibility: accept runtime-specific prompt additions without duplicating
  the base worker prompt.
- Modify: `src/atelier/worker/work_startup_runtime.py`
  Responsibility: preserve the public `worker_opening_prompt` facade while
  threading through runtime-specific prompt additions.
- Modify: `src/atelier/worker/runtime.py`
  Responsibility: extend the worker command adapter to pass runtime additions.
- Modify: `src/atelier/worker/session/agent.py`
  Responsibility: resolve worker runtime, append the worker runtime addendum to
  rendered `AGENTS.md`, and carry prompt additions forward to startup.
- Modify: `src/atelier/runtime_env.py`
  Responsibility: preserve explicit runtime-profile env if this slice exposes
  `ATELIER_RUNTIME_PROFILE`.
- Modify: `docs/behavior.md`
  Responsibility: document config shape, CLI options, and profile semantics.
- Modify: `README.md`
  Responsibility: document the new runtime option and example usage.

- Modify tests:
  `tests/atelier/test_config.py`
  `tests/atelier/commands/test_plan_cli.py`
  `tests/atelier/commands/test_work_cli.py`
  `tests/atelier/commands/test_plan.py`
  `tests/atelier/commands/test_work_runtime_wiring.py`
  `tests/atelier/worker/test_prompts.py`
  `tests/atelier/worker/test_session_agent.py`
  Responsibility: cover config defaults, CLI plumbing, planner/worker runtime
  selection, native parity, and trycycle-specific prompt/addendum behavior.

## Strategy gate

The wrong architecture would be to add `trycycle` as another `AgentSpec` in
`src/atelier/agents.py`. That would collapse two distinct concerns into one:
transport and runtime contract. Users still need to pick `codex` vs `claude`
independently of whether the session runs the native Atelier contract or the
trycycle-style contract, and the repo already has a lot of agent-specific logic
that should remain in one place.

The other wrong architecture would be to sprinkle `if runtime == "trycycle"`
branches directly through `plan.py`, `worker/prompts.py`, and
`worker/session/agent.py` without a shared runtime registry. That would make
native parity hard to prove and would make future runtime profiles expensive to
add.

The clean steady-state design is:

- keep `agents.AgentSpec` as the CLI transport registry
- add a separate runtime-profile layer with explicit per-role resolution
- keep native behavior encoded as the `native` profile
- implement `trycycle` as an Atelier-managed guidance profile in this slice
- let runtime profiles contribute only additive prompt and `AGENTS.md`
  contract text in this slice

That solves the user’s actual goal: explore and ship trycycle-like planner and
worker hardening without destabilizing the worker and planner lifecycle
machinery that already exists.

### Task 1: Add typed runtime-profile config and selection

**Files:**
- Create: `src/atelier/runtime_profiles/__init__.py`
- Create: `src/atelier/runtime_profiles/models.py`
- Create: `src/atelier/runtime_profiles/registry.py`
- Create: `tests/atelier/test_runtime_profiles.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Modify: `src/atelier/cli.py`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/commands/test_plan_cli.py`
- Modify: `tests/atelier/commands/test_work_cli.py`

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
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: FAIL because `AgentConfig` has no runtime field, the runtime registry
does not exist, and the CLI does not pass `runtime`.

- [ ] **Step 3: Write minimal implementation**

Add a typed runtime config that stays separate from the agent transport:

```python
RUNTIME_PROFILE_VALUES = ("native", "trycycle")
RuntimeProfileName = Literal["native", "trycycle"]


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
        if runtime_config.default:
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
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Tighten naming and docstrings, keep the new runtime helpers out of
`src/atelier/agents.py`, and verify the broader config/model surface.

Run:

```bash
uv run pytest \
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
  src/atelier/runtime_profiles/__init__.py \
  src/atelier/runtime_profiles/models.py \
  src/atelier/runtime_profiles/registry.py \
  src/atelier/models.py \
  src/atelier/config.py \
  src/atelier/cli.py \
  tests/atelier/test_runtime_profiles.py \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan_cli.py \
  tests/atelier/commands/test_work_cli.py
git commit -m "feat(runtime): add typed runtime profile selection" \
  -m "- add agent runtime config and precedence helpers" \
  -m "- expose runtime selection through plan and work CLI wiring" \
  -m "- cover defaults and CLI plumbing with tests"
```

### Task 2: Integrate planner runtime profiles without changing planner safety

**Files:**
- Create: `src/atelier/runtime_profiles/planner.py`
- Modify: `src/atelier/commands/plan.py`
- Modify: `tests/atelier/commands/test_plan.py`

- [ ] **Step 1: Identify or write the failing test**

Add planner tests for:

```python
def test_plan_cli_runtime_override_beats_config_runtime(...)
def test_plan_trycycle_runtime_appends_planner_contract_lines(...)
def test_plan_native_runtime_preserves_existing_opening_prompt(...)
```

The trycycle planner contract should require:

- explicit user-visible behavior capture
- explicit invariants and tricky-boundary analysis
- architecture decisions before changeset decomposition
- no weakening of planner read-only and teardown rules

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/atelier/commands/test_plan.py -k runtime -v
```

Expected: FAIL because planner runtime resolution and trycycle addenda do not
exist.

- [ ] **Step 3: Write minimal implementation**

Implement role-specific planner runtime content behind a small helper module,
for example:

```python
def planner_runtime_addendum(runtime_name: RuntimeProfileName) -> str:
    if runtime_name == "native":
        return ""
    return "\n".join(
        [
            "## Runtime Profile: trycycle",
            "- Own the first plan.",
            "- Capture user-visible behavior, invariants, tricky boundaries,",
            "  and cutover risk before changeset decomposition.",
            "- Make architecture decisions now; do not defer core reasoning",
            "  to later review rounds.",
        ]
    )
```

In `run_planner(...)`:

- resolve the planner runtime via the registry
- print `Planner runtime: <name>`
- append the runtime addendum to rendered planner `AGENTS.md`
- extend `_planner_opening_prompt(...)` to accept runtime-specific lines
- keep resume/session-id logic, sync monitor, guardrails, and teardown
  unchanged

If this slice exports `ATELIER_RUNTIME_PROFILE`, set it explicitly in the
planner env after sanitization rather than relying on ambient inheritance.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/atelier/commands/test_plan.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Re-run the full planner command suite to prove native parity.

Run:

```bash
uv run pytest \
  tests/atelier/commands/test_plan.py \
  tests/atelier/commands/test_plan_cli.py -v
```

Expected: all PASS, including the existing planner session/resume coverage.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/runtime_profiles/planner.py \
  src/atelier/commands/plan.py \
  tests/atelier/commands/test_plan.py
git commit -m "feat(plan): add planner runtime profiles" \
  -m "- resolve planner runtime separately from agent transport" \
  -m "- append trycycle planner contract lines to prompts and AGENTS output" \
  -m "- preserve planner resume and teardown behavior"
```

### Task 3: Integrate worker runtime profiles without changing worker lifecycle

**Files:**
- Create: `src/atelier/runtime_profiles/worker.py`
- Modify: `src/atelier/worker/prompts.py`
- Modify: `src/atelier/worker/work_startup_runtime.py`
- Modify: `src/atelier/worker/runtime.py`
- Modify: `src/atelier/worker/session/agent.py`
- Modify: `src/atelier/runtime_env.py`
- Modify: `tests/atelier/worker/test_prompts.py`
- Modify: `tests/atelier/worker/test_session_agent.py`
- Modify: `tests/atelier/commands/test_work_runtime_wiring.py`

- [ ] **Step 1: Identify or write the failing test**

Add worker-facing tests for:

```python
def test_worker_opening_prompt_includes_trycycle_contract_lines() -> None:
    prompt = worker_opening_prompt(..., runtime_lines=("Follow the plan task-by-task.",))
    assert "Follow the plan task-by-task." in prompt


def test_prepare_agent_session_appends_trycycle_worker_addendum(...) -> None:
    ...


def test_work_runtime_wiring_passes_runtime_override_to_worker_session(...) -> None:
    ...
```

The trycycle worker contract should require:

- execute only the seeded changeset
- derive a checklist from the bead contract before coding
- work task-by-task instead of broad free-form execution
- keep all existing finalize/publish/blocked semantics

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/commands/test_work_runtime_wiring.py -k runtime -v
```

Expected: FAIL because the worker prompt and session prep do not accept runtime
additions.

- [ ] **Step 3: Write minimal implementation**

Add runtime-specific worker content behind one helper module, for example:

```python
def worker_runtime_prompt_lines(runtime_name: RuntimeProfileName) -> tuple[str, ...]:
    if runtime_name == "native":
        return ()
    return (
        "Before coding, restate the bead contract as a concrete checklist.",
        "Execute the work task-by-task and keep the plan synchronized with the",
        "actual code and verification work.",
        "Do not skip required repo gates, push, or publish steps.",
    )
```

Then:

- resolve the worker runtime once in session preparation
- carry the resolved runtime name and prompt additions in
  `AgentSessionPreparation`
- append the worker addendum to rendered `AGENTS.md`
- extend `worker_opening_prompt(...)` to accept additive runtime lines
- keep startup selection, claim logic, worktree preparation, and finalize
  behavior unchanged
- if `ATELIER_RUNTIME_PROFILE` is exported for session tooling, add it to the
  allowlist in `runtime_env.USER_DEFAULT_ENV_KEYS`

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/commands/test_work_runtime_wiring.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run the broader worker startup and runtime suites to prove the new profile is
additive only.

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/worker/test_runtime.py \
  tests/atelier/commands/test_work.py \
  tests/atelier/commands/test_work_cli.py \
  tests/atelier/commands/test_work_runtime_wiring.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/runtime_profiles/worker.py \
  src/atelier/worker/prompts.py \
  src/atelier/worker/work_startup_runtime.py \
  src/atelier/worker/runtime.py \
  src/atelier/worker/session/agent.py \
  src/atelier/runtime_env.py \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/commands/test_work_runtime_wiring.py
git commit -m "feat(work): add worker runtime profiles" \
  -m "- thread runtime selection through worker session preparation" \
  -m "- add trycycle worker contract lines without changing lifecycle logic" \
  -m "- preserve worker runtime env and prompt compatibility"
```

### Task 4: Document the contract and lock down regression coverage

**Files:**
- Create: `docs/trycycle-runtime-contract.md`
- Modify: `docs/behavior.md`
- Modify: `README.md`
- Modify: `tests/atelier/test_config.py`
- Modify: `tests/atelier/commands/test_plan.py`
- Modify: `tests/atelier/worker/test_session_agent.py`

- [ ] **Step 1: Identify or write the failing test**

Add or extend tests that prove the intended end-state contract:

- config without `agent.runtime` still behaves as native
- planner native runtime keeps the existing prompt wording
- worker native runtime keeps the existing prompt wording
- trycycle runtime is additive and role-scoped

Use existing tests instead of inventing doc-only coverage where possible.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py -k "runtime or native" -v
```

Expected: FAIL until the native-parity and role-scoped assertions exist and
pass.

- [ ] **Step 3: Write minimal implementation**

Document the behavior explicitly:

- `docs/behavior.md`
  Add the new config shape and `--runtime` command behavior.
- `docs/trycycle-runtime-contract.md`
  Record the invariant that runtime profiles alter only session guidance in
  this slice.
- `README.md`
  Add one short example for planner and worker usage:

```bash
atelier plan --runtime trycycle
atelier work --runtime trycycle
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py -k "runtime or native" -v
```

Expected: PASS.

- [ ] **Step 5: Refactor and verify**

Run the repo-required gates for the completed slice.

Run:

```bash
just test
just format
just lint
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  docs/trycycle-runtime-contract.md \
  docs/behavior.md \
  README.md \
  tests/atelier/test_config.py \
  tests/atelier/commands/test_plan.py \
  tests/atelier/worker/test_session_agent.py
git commit -m "docs(runtime): document trycycle runtime profiles" \
  -m "- document config and command behavior for runtime profiles" \
  -m "- lock down native-parity and trycycle runtime regression coverage" \
  -m "- add README examples for planner and worker runtime selection"
```

## Final verification and landing

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

## Why this plan is the right cutover

- It lands the full feature directly: a real per-role runtime option with a
  shipped `trycycle` profile.
- It avoids the main design mistake of conflating runtime behavior with agent
  transport.
- It keeps native behavior stable and testable.
- It gives Atelier a clean extension point for future runtime profiles or a
  later external runtime wrapper, without forcing that dependency into the
  first cut.
