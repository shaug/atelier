# Trycycle-Bounded Runtime Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use trycycle-executing to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Add a role-scoped `runtime profile` system so `atelier plan` and
`atelier work` can opt into a bounded `trycycle-bounded` behavior without
changing default Atelier semantics or requiring a local trycycle installation.

**Architecture:** Keep the profile as an Atelier-owned selection layer. The
selected profile is stored in project user config, resolved separately for the
planner and worker roles, and threaded into the existing command/session
boundaries. Durable state stays in Beads and workspace metadata; nested helper
sessions are internal worker implementation details, not a new shared
coordinator. If the bounded profile cannot satisfy the current worker
semantics, it must fail closed with explicit evidence instead of silently
broadening scope or mutating workspace identity.

**Tech Stack:** Python 3.11, Pydantic models, Typer CLI, Beads/`bd`, existing
Atelier templates and skills.

---

### Task 1: Add runtime profile config and CLI plumbing

**Files:**
- Create: `src/atelier/runtime_profiles.py`
- Modify: `src/atelier/models.py`
- Modify: `src/atelier/config.py`
- Modify: `src/atelier/commands/config.py`
- Modify: `src/atelier/commands/plan.py`
- Modify: `src/atelier/commands/work.py`
- Modify: `src/atelier/cli.py`
- Test: `tests/atelier/test_models.py`
- Test: `tests/atelier/test_config.py`
- Test: `tests/atelier/commands/test_config.py`
- Test: `tests/atelier/commands/test_plan_cli.py`
- Test: `tests/atelier/commands/test_work_cli.py`
- Test: `tests/atelier/test_runtime_profiles.py`

- [ ] **Step 1: Identify or write the failing test**

  Add tests for:
  - `runtime.planner.profile` and `runtime.worker.profile` parsing.
  - default `standard` values for new projects.
  - unknown profile rejection.
  - `atelier plan --runtime-profile ...` and `atelier work --runtime-profile ...`
    flag plumbing.
  - `atelier config` round-tripping the new `runtime` section.

  Run:

  ```bash
  pytest tests/atelier/test_models.py tests/atelier/test_config.py \
    tests/atelier/commands/test_config.py tests/atelier/commands/test_plan_cli.py \
    tests/atelier/commands/test_work_cli.py tests/atelier/test_runtime_profiles.py -v
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run the same command and confirm the failure is about missing runtime profile
  model/config/flag handling.

- [ ] **Step 3: Write minimal implementation**

  - Add `RuntimeConfig` and role-specific runtime profile models.
  - Preserve runtime selections in `ProjectConfig` and `ProjectUserConfig`.
  - Update config split/merge/default/prompt helpers to carry the new section.
  - Add the shared runtime profile registry and validation helpers.
  - Thread `--runtime-profile` through the `plan` and `work` CLI controllers.
  - Default new typed runtime fields to `standard` so existing callers stay
    valid until they opt into a profile explicitly.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest tests/atelier/test_models.py tests/atelier/test_config.py \
    tests/atelier/commands/test_config.py tests/atelier/commands/test_plan_cli.py \
    tests/atelier/commands/test_work_cli.py tests/atelier/test_runtime_profiles.py -v
  ```

- [ ] **Step 5: Refactor and verify**

  Tighten the config merge/split behavior, confirm the default `standard`
  profile remains unchanged, and then run the broader config/CLI slice:

  ```bash
  pytest tests/atelier/test_models.py tests/atelier/test_config.py \
    tests/atelier/commands/test_config.py tests/atelier/commands/test_plan_cli.py \
    tests/atelier/commands/test_work_cli.py tests/atelier/test_runtime_profiles.py -v
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add src/atelier/runtime_profiles.py src/atelier/models.py src/atelier/config.py \
    src/atelier/commands/config.py src/atelier/commands/plan.py \
    src/atelier/commands/work.py src/atelier/cli.py \
    tests/atelier/test_models.py tests/atelier/test_config.py \
    tests/atelier/commands/test_config.py tests/atelier/commands/test_plan_cli.py \
    tests/atelier/commands/test_work_cli.py tests/atelier/test_runtime_profiles.py
  git commit -m "feat(runtime): add role-scoped runtime profiles"
  ```

### Task 2: Add the planner runtime profile contract

**Files:**
- Create: `src/atelier/planner_runtime_profile.py`
- Modify: `src/atelier/commands/plan.py`
- Modify: `src/atelier/templates/AGENTS.planner.md.tmpl`
- Test: `tests/atelier/commands/test_plan.py`
- Test: `tests/atelier/test_planner_agents_template.py`

- [ ] **Step 1: Identify or write the failing test**

  Add tests that prove planner runs surface the selected runtime profile in the
  planner opening prompt, template context, and bead/session metadata. The
  `trycycle-bounded` profile should also produce a stricter bead contract with
  explicit intent, non-goals, constraints, success criteria, and test
  expectations.

  Run:

  ```bash
  pytest tests/atelier/commands/test_plan.py tests/atelier/test_planner_agents_template.py -v
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run the same command and confirm the planner profile fields are still missing
  from the current implementation.

- [ ] **Step 3: Write minimal implementation**

  - Add a planner profile helper that renders the bounded bead contract.
  - Keep workspace identity and startup-teardown behavior unchanged.
  - Record the chosen planner runtime profile in planner launch metadata.
  - Update `AGENTS.planner.md.tmpl` so the selected profile is visible to the
    planner agent.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest tests/atelier/commands/test_plan.py tests/atelier/test_planner_agents_template.py -v
  ```

- [ ] **Step 5: Refactor and verify**

  Tighten the planner contract wording so it is explicit but still bounded, and
  then rerun the planner slice above.

- [ ] **Step 6: Commit**

  ```bash
  git add src/atelier/planner_runtime_profile.py src/atelier/commands/plan.py \
    src/atelier/templates/AGENTS.planner.md.tmpl \
    tests/atelier/commands/test_plan.py tests/atelier/test_planner_agents_template.py
  git commit -m "feat(plan): add planner runtime profile contract"
  ```

### Task 3: Add the bounded worker runtime profile

**Files:**
- Create: `src/atelier/worker/work_runtime_profile.py`
- Modify: `src/atelier/worker/context.py`
- Modify: `src/atelier/worker/prompts.py`
- Modify: `src/atelier/worker/session/startup.py`
- Modify: `src/atelier/worker/session/agent.py`
- Modify: `src/atelier/worker/session/runner.py`
- Modify: `src/atelier/worker/work_startup_runtime.py`
- Modify: `src/atelier/worker/runtime.py`
- Modify: `src/atelier/templates/AGENTS.worker.md.tmpl`
- Test: `tests/atelier/worker/test_context.py`
- Test: `tests/atelier/worker/test_session_startup.py`
- Test: `tests/atelier/worker/test_session_agent.py`
- Test: `tests/atelier/worker/test_session_runner_flow.py`
- Test: `tests/atelier/worker/test_runtime.py`
- Test: `tests/atelier/test_worker_agents_template.py`

- [ ] **Step 1: Identify or write the failing test**

  Add tests for:
  - worker runtime profile propagation through typed worker contexts.
  - runtime metadata visible in the worker launch environment and template.
  - bounded helper-session behavior.
  - fail-closed outcomes when the contract cannot converge.

  Run:

  ```bash
  pytest tests/atelier/worker/test_context.py \
    tests/atelier/worker/test_session_startup.py \
    tests/atelier/worker/test_session_agent.py \
    tests/atelier/worker/test_session_runner_flow.py \
    tests/atelier/worker/test_runtime.py \
    tests/atelier/test_worker_agents_template.py -v
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run the same command and confirm the missing worker profile behavior is the
  reason for failure.

- [ ] **Step 3: Write minimal implementation**

  - Thread the selected runtime profile through the worker contexts.
  - Add bounded worker-loop helpers that can run nested helper sessions inside
    one worker-owned bead session.
  - Add defaulted runtime-profile fields to worker typed contexts so existing
    call sites keep working while the new profile is threaded through.
  - Persist phase evidence in Beads description fields instead of chat history.
  - Keep shared workspace identifiers and durable work selection unchanged.
  - Fail closed with explicit blocked evidence when the bounded loop cannot
    prove convergence.
  - Update `AGENTS.worker.md.tmpl` so the selected profile is visible to the
    worker agent.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest tests/atelier/worker/test_context.py \
    tests/atelier/worker/test_session_startup.py \
    tests/atelier/worker/test_session_agent.py \
    tests/atelier/worker/test_session_runner_flow.py \
    tests/atelier/worker/test_runtime.py \
    tests/atelier/test_worker_agents_template.py -v
  ```

- [ ] **Step 5: Refactor and verify**

  Tighten the bounded-loop budget, evidence capture, and helper-session
  boundary so the implementation stays Atelier-owned rather than becoming a
  generic coordinator. Then rerun the worker slice above.

- [ ] **Step 6: Commit**

  ```bash
  git add src/atelier/worker/work_runtime_profile.py src/atelier/worker/context.py \
    src/atelier/worker/prompts.py src/atelier/worker/session/startup.py \
    src/atelier/worker/session/agent.py src/atelier/worker/session/runner.py \
    src/atelier/worker/work_startup_runtime.py src/atelier/worker/runtime.py \
    src/atelier/templates/AGENTS.worker.md.tmpl \
    tests/atelier/worker/test_context.py tests/atelier/worker/test_session_startup.py \
    tests/atelier/worker/test_session_agent.py \
    tests/atelier/worker/test_session_runner_flow.py \
    tests/atelier/worker/test_runtime.py tests/atelier/test_worker_agents_template.py
  git commit -m "feat(worker): add bounded trycycle runtime profile"
  ```

### Task 4: Update docs and run the repo gates

**Files:**
- Modify: `docs/behavior.md`
- Modify: `docs/SPEC.md`
- Modify: `docs/worker-runtime-architecture.md`

- [ ] **Step 1: Update the docs**

  Document:
  - the new `runtime` config section and its role-scoped defaults;
  - the bounded `trycycle-bounded` profile and what it does not change;
  - the worker/planner mismatch boundary and the fail-closed outcome when the
    worker cannot converge.

- [ ] **Step 2: Run the full test suite**

  ```bash
  just test
  ```

- [ ] **Step 3: Run formatting**

  ```bash
  just format
  ```

- [ ] **Step 4: Run lint**

  ```bash
  just lint
  ```

- [ ] **Step 5: Verify the worktree is clean enough to commit**

  Confirm the final diff only contains the runtime profile plan follow-through
  and the docs/tests needed to support it.

- [ ] **Step 6: Commit**

  ```bash
  git add docs/behavior.md docs/SPEC.md docs/worker-runtime-architecture.md
  git commit -m "docs(runtime): describe bounded trycycle profile"
  ```

## Risks and guardrails

- Do not add a global `trycycle` dependency or a hidden runtime switch.
- Do not change shared workspace identifiers, worktree mappings, or Beads
  ownership semantics.
- Do not move durable state into helper-session transcripts.
- Do not weaken the current worker finalization gates.
- Keep `standard` as the default profile so existing behavior stays intact.
- If the bounded profile cannot be expressed without a new coordination model,
  fail closed and document the mismatch instead of inventing a global
  coordinator.

## References

This plan is grounded in [Behavior and Design Notes],
[Projected Skill Runtime Contract], [Service Tier Proposal], and
[Worker Runtime Architecture].

<!-- inline reference link definitions. please keep alphabetized -->

[behavior and design notes]: ../behavior.md
[projected skill runtime contract]: ../projected-skill-runtime-contract.md
[service tier proposal]: ../service-tier-proposal.md
[worker runtime architecture]: ../worker-runtime-architecture.md
