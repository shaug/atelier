# Trycycle-Bounded Runtime Profile Plan

## Summary

Atelier will gain a first-class `runtime profile` layer that is selected per
role and resolves before planner or worker orchestration begins. The initial
shipped profile is `trycycle-bounded`, an Atelier-owned adaptation of the
trycycle feedback-loop model that hardens planning and worker execution while
preserving Atelier's durable Beads, worktree, PR, and operator-accountability
semantics.

Default behavior must remain unchanged. When no runtime profile override is
present, planner and worker flows continue to behave exactly as they do today.

## Locked Decisions

- Canonical terminology is `runtime profile`.
- Source of truth is repo-owned code, templates, and shipped skill assets, not
  ambient local files.
- Shared workspace identifiers stay stable across runtime profiles.
- Multiple workers may process available Atelier work items concurrently, each
  resolving its own worker runtime profile.
- The bounded form is acceptable as a first-class outcome. If the profile
  cannot converge, the worker must block with evidence instead of silently
  falling back.

## Why This Is Feasible

The trycycle model is feasible in Atelier only when it is treated as a
worker-internal orchestration strategy and not as a replacement for Atelier's
message/ticket system. The durable source of truth remains Beads plus the git
workspace state. The profile can therefore harden the plan and execution loops
without changing the fact that Atelier coordinates work through local beads,
reviewable changesets, and PR/lifecycle state.

That means the implementation should resolve the mismatch, not hide it:

- Trycycle-style subagent communication becomes explicit nested agent sessions
  owned by one worker runtime.
- Ephemeral conversation output is never the source of truth.
- Finalization still obeys current Atelier north-star, review, PR, and
  integration gates.
- Planning and worker selection stay role-scoped so profile choice does not
  mutate shared workspace identity.

## Mismatch Contract

- Trycycle assumes a loop-centric execution model. Atelier must keep durable
  work coordination in Beads, so the loop will persist its checkpoints and
  evidence as bead fields and notes instead of chat history.
- Trycycle assumes a relatively self-contained agent loop. Atelier may run
  multiple workers at once, so profile resolution is per session and never a
  global coordinator.
- Trycycle biases toward task completion. Atelier biases toward operator
  accountability, reviewability, and human-sized changesets, so the profile
  must stop or split work when the bead contract is too large.
- Trycycle can be treated as an internal strategy. Atelier must not depend on a
  global trycycle installation or user-local state to preserve behavior.

## User-Facing Behavior

`atelier plan` and `atelier work` gain role-local `--runtime-profile`
selection. The selected value overrides the project default for that command's
role only. A missing override resolves to the configured role default, and an
unknown profile fails loudly.

The `atelier config` surface must expose the chosen planner and worker profile
values so users can inspect and edit them without editing JSON by hand. New
projects should seed both roles to `standard`.

The `trycycle-bounded` profile must be visible in emitted launch metadata so a
user can tell which runtime strategy produced the current planner or worker
session.

The config shape for the first release should be explicit and small:

- `runtime.planner.profile`
- `runtime.worker.profile`

Those values live in the user-editable project config. The profile definitions
themselves stay repo-owned and versioned in code.

## Architecture

The implementation should add a dedicated runtime-profile contract layer and
keep `src/atelier/commands/*.py` thin. Command modules should resolve the
profile and hand the result to profile-specific orchestration code instead of
branching on runtime behavior themselves.

Profile definitions should live in repo-owned code, with profile-scoped skill
and template assets shipped alongside the tool and projected into the agent
runtime in the same deterministic way as the existing Atelier skills. That
keeps the behavior versioned with the release and avoids local user-state
drift.

The profile contract should be role-scoped:

- planner profile: shapes the bead contract and planner handoff semantics
- worker profile: owns the execution loop, bounded subagent use, and evidence
  capture

A clean module split for the new logic should be:

- `src/atelier/runtime_profiles.py` for registry and shared profile contracts
- `src/atelier/planner/runtime_profile.py` for planner-specific contract
  rendering
- `src/atelier/worker/runtime_profile.py` for worker-specific loop orchestration

Those modules should stay small; if either role-specific module starts to grow
substantially, split the orchestration helpers before the controller modules
become policy-heavy.

The default `standard` profile should reuse current behavior with no functional
changes.

## Planner Profile Shape

The planner side of `trycycle-bounded` should make bead plans more explicit and
machine-consumable. It should produce a stricter contract that includes the
intent, non-goals, constraints, success criteria, test expectations, and any
worker hardening requirements before work begins.

Planner output should also make the split decision earlier when the requested
scope is too large for a reviewable changeset. The profile should not wait for a
worker to discover that the work is oversized.

Planner runtime changes should:

- render the profile-specific bead contract from repo-owned templates or skill
  assets
- preserve the existing startup-check and planner teardown semantics
- keep session identity and workspace selection unchanged
- record the selected runtime profile in the planner session metadata

## Worker Profile Shape

The worker side of `trycycle-bounded` is the main behavior change. It should
act as the orchestrator for one selected bead and may use nested subagent
sessions as implementation helpers inside the worker runtime.

The worker loop should be bounded and explicit:

- verify the bead contract before implementation starts
- refine the plan when the contract is incomplete or ambiguous
- execute implementation steps with optional nested subagent help
- run local test/review loops until the contract is satisfied or the budget is
  exhausted
- record phase evidence durably in Beads
- finalize only when current Atelier semantics allow it

Subagent use must be contained inside the worker session. The worker may spawn
subagent sessions for targeted tasks, but their outputs are only evidence until
they are reduced into Beads notes or fields. No subagent transcript becomes the
system of record.

The bounded profile must fail closed when:

- the bead contract is incomplete and cannot be repaired within budget
- subagent output contradicts the bead contract or selected scope
- the worker cannot prove convergence before the loop budget expires
- the finalization gates still fail after the bounded loop completes

The terminal outcome in those cases should be an explicit blocked state with
evidence and next-step guidance, not a silent success or hidden retry.

## Planned Code Changes

- Add a runtime-profile model to project config and config resolution.
- Add CLI plumbing so `plan` and `work` can override the role default with an
  explicit runtime profile.
- Add a runtime-profile registry with a stable built-in `standard` profile and
  a `trycycle-bounded` profile.
- Add config defaults so new projects seed `runtime.planner.profile` and
  `runtime.worker.profile` as `standard`.
- Add planner-side contract rendering helpers for profile-specific bead
  requirements.
- Add worker-side orchestration helpers that select and run the profile's loop
  strategy.
- Extend Beads description-field helpers so profile evidence and handoff
  metadata can be stored durably in existing bead records.
- Update planner and worker templates so the shipped runtime assets describe the
  selected profile clearly.
- Keep the existing default plan/work paths intact for the `standard` profile.

## Acceptance Criteria

- Existing planner and worker behavior remains unchanged when the default
  `standard` profile is in effect.
- The project config can persist planner and worker runtime profile choices and
  load old configs that do not yet have the new section.
- `atelier plan --runtime-profile trycycle-bounded` resolves the profile and
  emits the stricter bead contract.
- `atelier work --runtime-profile trycycle-bounded` runs the bounded worker
  orchestration path and records phase evidence durably.
- The worker profile can use nested subagent sessions without changing shared
  workspace identifiers or durable work selection.
- Finalization still obeys current north-star, PR, and integration gates.
- `atelier config` can round-trip the new runtime section without losing
  existing user config fields.
- A bounded loop that cannot converge ends in a blocked, evidence-rich state.
- The new profile surface is documented for users and future maintainers.

## Verification

The implementation should be protected by a hybrid floor:

- config and profile-resolution unit tests for defaults, overrides, and unknown
  profile failures
- planner and worker wiring tests that prove the commands resolve the selected
  profile without disturbing existing defaults
- scenario tests that exercise the bounded worker loop and assert durable
  Beads evidence, not just internal helper calls
- regression tests that prove shared workspace identifiers and current
  finalization semantics do not change under profile selection

The default-path regression suite should remain the source of truth for
unchanged Atelier behavior.

## Risks and Guardrails

- Do not let runtime profile selection become a hidden global state knob.
- Do not move durable state into subagent transcripts.
- Do not weaken the current worker finalization gates in the name of profile
  flexibility.
- Do not require a local trycycle installation to make the profile work.
- Do not expand the profile layer into a generic policy framework. It should
  stay a small, explicit selection layer with a bounded set of built-in
  profiles.
- Keep any new modules small and focused. If orchestration logic starts to
  crowd a module, split it rather than letting `commands/` or `worker/`
  accrete policy.

## References

This plan is grounded in [Behavior and Design Notes],
[Projected Skill Runtime Contract], [Service Tier Proposal],
[Worker Runtime Architecture], and [Worker Worktree Startup Contract].

<!-- inline reference link definitions. please keep alphabetized -->

[behavior and design notes]: ../behavior.md
[projected skill runtime contract]: ../projected-skill-runtime-contract.md
[service tier proposal]: ../service-tier-proposal.md
[worker runtime architecture]: ../worker-runtime-architecture.md
[worker worktree startup contract]: ../worker-worktree-startup-contract.md
