# Trycycle Runtime Profiles for Planner and Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Add a first-class runtime profile option to `atelier plan` and
`atelier work` so users can choose either the native Atelier contract or a
trycycle-derived contract on top of the existing agent CLI, with native
behavior preserved as the default.

**Architecture:** Introduce typed runtime-profile configuration and a shared
runtime registry that is distinct from `agent.default`, then thread the
selected profile into planner and worker launch preparation. Native remains the
zero-behavior-change profile; the new `trycycle` profile adds role-specific
prompt and `AGENTS.md` addenda derived from the local trycycle skill docs
without changing Beads, worktree, claim, teardown, or publish semantics.
Planner session resume also becomes runtime-aware so switching between
`native` and `trycycle` never silently resumes a planner session that was
started under a different contract.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pytest, existing Atelier
planner/worker runtime modules, local trycycle skill markdown sources.

---

## Execution prerequisites

- Run `bash .githooks/worktree-bootstrap.sh` in this worktree before the first
  code change so repo-local hooks are bootstrapped here as required by
  `AGENTS.md`.
- Treat these local skill docs as the authoritative trycycle references for the
  shipped `trycycle` runtime text in this slice:
  - `/Users/scott/.codex/skills/trycycle/subskills/trycycle-planning/SKILL.md`
  - `/Users/scott/.codex/skills/trycycle/subskills/trycycle-executing/SKILL.md`
  - `/Users/scott/.codex/skills/trycycle/subskills/trycycle-finishing/SKILL.md`
- Do not invent a new `ATELIER_*` environment contract for runtime profiles in
  this slice. Keep the runtime signal in config, CLI output, prompts, and
  rendered `AGENTS.md` only.

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

- Runtime profiles may change agent guidance, prompt construction, and rendered
  `AGENTS.md` content. They must not change:
  Beads schema, worktree ownership, claim rules, planner sync, teardown,
  publish/finalize, or runtime environment sanitization semantics.
- Resume behavior remains agent-defined. The runtime profile must not change
  how saved Codex planner session IDs are discovered or persisted when the
  runtime profile is unchanged. A runtime-profile change must intentionally
  bypass resume to avoid reviving stale planner context from the wrong
  contract.
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
  Responsibility: planner runtime text derived from the local trycycle planning
  skill, plus planner session namespace helpers.
- Create: `src/atelier/runtime_profiles/worker.py`
  Responsibility: worker runtime text derived from the local trycycle
  executing/finishing skills.
- Create: `tests/atelier/test_runtime_profiles.py`
  Responsibility: config parsing and runtime selection precedence coverage.
- Create: `docs/trycycle-runtime-contract.md`
  Responsibility: durable contract for native vs `trycycle` runtime behavior
  and the specific trycycle-derived obligations shipped in this slice.

- Modify: `src/atelier/models.py`
  Responsibility: add typed runtime config to `AgentConfig`.
- Modify: `src/atelier/config.py`
  Responsibility: preserve runtime config through defaults and config rebuilds.
- Modify: `src/atelier/cli.py`
  Responsibility: expose `--runtime` on `plan` and `work`.
- Modify: `src/atelier/commands/plan.py`
  Responsibility: resolve planner runtime, surface it to the user, append the
  planner runtime addendum to rendered `AGENTS.md`, augment the opening
  prompt, and keep planner resume scoped to the selected runtime profile.
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
  Responsibility: resolve worker runtime, append the worker runtime addendum to
  rendered `AGENTS.md`, and carry prompt additions forward to startup.
- Modify: `src/atelier/worker/session/runner.py`
  Responsibility: surface the selected worker runtime in startup output and use
  the runtime-specific prompt additions from session preparation.
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
  `tests/atelier/worker/test_session_runner.py`
  `tests/atelier/worker/test_session_runner_flow.py`
  Responsibility: cover config defaults, CLI plumbing, planner/worker runtime
  selection, native parity, and trycycle-specific prompt/addendum behavior.

## Strategy gate

The wrong architecture would be to add `trycycle` as another `AgentSpec` in
`src/atelier/agents.py`. That would collapse two distinct concerns into one:
transport and runtime contract. Users still need to pick `codex` vs `claude`
independently of whether the session runs the native Atelier contract or the
trycycle-style contract, and the repo already has a lot of agent-specific
logic that should remain in one place.

The other wrong architecture would be to sprinkle `if runtime == "trycycle"`
branches directly through `plan.py`, `worker/prompts.py`, and
`worker/session/agent.py` without a shared runtime registry. That would make
native parity hard to prove and would make future runtime profiles expensive to
add.

The third wrong architecture would be to ship a profile named `trycycle`
without grounding its text in the local trycycle skill sources. That would
turn the feature into arbitrary prompt tweaks rather than a deliberate
trycycle-like runtime option.

The clean steady-state design is:

- keep `agents.AgentSpec` as the CLI transport registry
- add a separate runtime-profile layer with explicit per-role resolution
- keep native behavior encoded as the `native` profile
- implement `trycycle` as an Atelier-managed guidance profile in this slice
- derive the shipped trycycle planner and worker obligations from the local
  trycycle skill docs and codify them in repo-owned helper modules and docs
- do not add a new environment variable surface unless a concrete follow-on
  requirement appears

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

- [ ] **Step 5: Refactor, format, and verify**

Tighten naming and docstrings, keep the new runtime helpers out of
`src/atelier/agents.py`, run the repo formatter before committing, and verify
the broader config/model surface.

Run:

```bash
just format
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
def test_plan_runtime_change_starts_fresh_planner_session(...)
def test_plan_runtime_scopes_codex_session_lookup(...)
```

The trycycle planner contract must be derived from
`/Users/scott/.codex/skills/trycycle/subskills/trycycle-planning/SKILL.md`
and should require:

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

Implement role-specific planner runtime content behind a small helper module.
Base the `trycycle` text on the local trycycle planning skill instead of
inventing new obligations. For example:

```python
def planner_runtime_addendum(runtime_name: RuntimeProfileName) -> str:
    if runtime_name == "native":
        return ""
    return "\n".join(
        [
            "## Runtime Profile: trycycle",
            "- Diagnose the plan completely before deciding anything.",
            "- Capture user-visible behavior, invariants, and failure modes",
            "  before changeset decomposition.",
            "- Make architecture decisions now; do not defer core reasoning",
            "  to later review rounds.",
        ]
    )
```

Add planner runtime-specific session metadata helpers, for example:

```python
_PLANNER_SESSION_RUNTIME_FIELD = "planner_session.runtime"


def planner_workspace_uid(
    *,
    agent_home_name: str,
    runtime_name: RuntimeProfileName,
) -> str:
    return f"planner-{agent_home_name}-{runtime_name}"
```

In `run_planner(...)`:

- resolve the planner runtime via the registry
- print `Planner runtime: <name>`
- compute the planner workspace/session namespace from the selected runtime
- append the runtime addendum to rendered planner `AGENTS.md`
- extend `_planner_opening_prompt(...)` to accept runtime-specific lines
- persist both planner session id and planner runtime when Codex returns a
  session id
- if the saved planner runtime differs from the selected runtime, bypass
  resume, clear the stale saved session pointer, and start a fresh session
  under the selected runtime namespace
- keep resume/session-id logic, sync monitor, guardrails, and teardown
  otherwise unchanged

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/atelier/commands/test_plan.py -k runtime -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

Re-run the full planner command suite to prove native parity.

Run:

```bash
just format
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

### Task 3: Integrate worker runtime profiles

**Files:**
- Create: `src/atelier/runtime_profiles/worker.py`
- Modify: `src/atelier/worker/ports.py`
- Modify: `src/atelier/worker/prompts.py`
- Modify: `src/atelier/worker/work_startup_runtime.py`
- Modify: `src/atelier/worker/runtime.py`
- Modify: `src/atelier/worker/session/agent.py`
- Modify: `src/atelier/worker/session/runner.py`
- Modify: `tests/atelier/worker/test_prompts.py`
- Modify: `tests/atelier/worker/test_session_agent.py`
- Modify: `tests/atelier/worker/test_session_runner.py`
- Modify: `tests/atelier/worker/test_session_runner_flow.py`
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


def test_worker_session_runner_reports_selected_runtime(...) -> None:
    ...
```

The trycycle worker contract must be derived from:

- `/Users/scott/.codex/skills/trycycle/subskills/trycycle-executing/SKILL.md`
- `/Users/scott/.codex/skills/trycycle/subskills/trycycle-finishing/SKILL.md`

It should require:

- execute only the seeded changeset
- derive a checklist from the bead contract before coding
- work task-by-task instead of broad free-form execution
- keep all existing finalize, push, and publish semantics

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/commands/test_work_runtime_wiring.py -k runtime -v
```

Expected: FAIL because the worker prompt and session prep do not accept runtime
additions.

- [ ] **Step 3: Write minimal implementation**

Add runtime-specific worker content behind one helper module. Base the
`trycycle` lines on the local trycycle executing and finishing skills instead
of ad hoc wording. For example:

```python
def worker_runtime_prompt_lines(
    runtime_name: RuntimeProfileName,
) -> tuple[str, ...]:
    if runtime_name == "native":
        return ()
    return (
        "Before coding, restate the bead contract as a concrete checklist.",
        "Execute the work task-by-task and keep the plan synchronized with",
        "the actual code and verification work.",
        "Do not skip required repo gates, push, or publish steps.",
    )
```

Then:

- resolve the worker runtime once in session preparation
- carry the resolved runtime name and prompt additions in
  `AgentSessionPreparation`
- extend the worker command/service protocols so runner code can receive the
  runtime-specific prompt additions without ad hoc attribute access
- append the worker addendum to rendered `AGENTS.md`
- extend `worker_opening_prompt(...)` to accept additive runtime lines
- surface `Worker runtime: <name>` in startup output before the agent session
  begins so the active contract is visible to the user
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
  tests/atelier/commands/test_work.py \
  tests/atelier/commands/test_work_cli.py \
  tests/atelier/commands/test_work_runtime_wiring.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/atelier/runtime_profiles/worker.py \
  src/atelier/worker/ports.py \
  src/atelier/worker/prompts.py \
  src/atelier/worker/work_startup_runtime.py \
  src/atelier/worker/runtime.py \
  src/atelier/worker/session/agent.py \
  src/atelier/worker/session/runner.py \
  tests/atelier/worker/test_prompts.py \
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py \
  tests/atelier/worker/test_session_runner_flow.py \
  tests/atelier/commands/test_work_runtime_wiring.py
git commit -m "feat(work): add worker runtime profiles" \
  -m "- thread runtime selection through worker session preparation" \
  -m "- add trycycle worker contract lines without changing lifecycle logic" \
  -m "- preserve worker prompt and session-runner compatibility"
```

### Task 4: Document the contract, lock down regression coverage, and land it

**Files:**
- Create: `docs/trycycle-runtime-contract.md`
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

- `docs/trycycle-runtime-contract.md`
  Record the specific planner obligations derived from the local trycycle
  planning skill, the worker obligations derived from the local trycycle
  executing/finishing skills, and the invariant that runtime profiles alter
  only session guidance in this slice.
- `docs/behavior.md`
  Add the new config shape and `--runtime` command behavior.
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
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py -k "runtime or native" -v
```

Expected: PASS.

- [ ] **Step 5: Refactor, format, and verify**

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
  tests/atelier/worker/test_session_agent.py \
  tests/atelier/worker/test_session_runner.py
git commit -m "docs(runtime): document trycycle runtime profiles" \
  -m "- document config and command behavior for runtime profiles" \
  -m "- codify the shipped trycycle-derived planner and worker contract text" \
  -m "- lock down native-parity and role-scoped regression coverage"
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
- It grounds the `trycycle` profile in actual local trycycle source material
  instead of ad hoc prompt wording.
- It keeps native behavior stable and testable.
- It avoids creating a new environment-variable surface before one is
  justified.
