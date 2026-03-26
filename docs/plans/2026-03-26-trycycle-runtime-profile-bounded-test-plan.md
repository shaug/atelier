## Harness requirements

- Recording runtime executable fixture. This is a tiny test-only binary or
  script that Atelier launches through the new runtime-profile path. It must
  record argv, cwd, env, stdin/prompt payload, optional session id, and exit
  status to files so tests can assert the real launch boundary. Complexity:
  moderate. Tests 3 through 7 depend on it.
- Project and Beads scenario fixture. Existing temp-repo helpers can seed
  `config.sys.json`, `config.user.json`, project-scoped Beads, and worktree
  mappings. This fixture exposes the user-visible source of truth for config
  round-trips, planner/worker state, and teardown effects. Complexity: low.
  Tests 1 through 7 depend on it.

## Test plan

1. Name: `atelier config` preserves the new runtime section and defaults both
   roles to `standard`
   Type: regression
   Disposition: new
   Harness: project/config round-trip fixture plus the existing `atelier config`
   command surface
   Preconditions: a temp project with config files missing any `runtime`
   section, or an existing config with unrelated user fields already set
   Actions: run `atelier config --prompt` and `atelier config --edit` against
   the temp project, then read back `config.user.json` and the JSON output from
   `atelier config`
   Expected outcome: the written user config contains `runtime.planner.profile`
   and `runtime.worker.profile` set to `standard`; unrelated user fields remain
   unchanged; the command output includes the runtime section because the
   source of truth says the runtime profile is user-managed config, not an
   implicit default. Source of truth: [Specification], [Behavior and Design
   Notes], and the implementation plan's config task
   Interactions: JSON serialization, prompt/edit code paths, config split and
   merge logic, and file-system writes to `config.user.json`

2. Name: invalid runtime profiles fail before planner or worker launch
   Type: boundary
   Disposition: new
   Harness: model validation plus CLI command parsing
   Preconditions: a temp project config or CLI invocation that supplies an
   unknown runtime profile such as `bogus`
   Actions: parse the config models directly, then invoke `atelier plan
   --runtime-profile bogus` and `atelier work --runtime-profile bogus`
   Expected outcome: validation fails with a loud error and a non-zero exit;
   the planner or worker session is not started; no AGENTS file or Beads state
   is mutated. Source of truth: the implementation plan's "unknown profile
   rejection" requirement and the repo's fail-closed CLI contract
   Interactions: Typer option parsing, Pydantic validation, and the config
   loader

3. Name: `atelier plan --runtime-profile trycycle-bounded` launches the bounded
   planner contract and records the selected profile
   Type: scenario
   Disposition: new
   Harness: recording runtime executable plus a seeded planner/beads scenario
   Preconditions: a temp project with one deferred epic that is ready to be
   planned, a project-scoped Beads store, and the new runtime profile selected
   for the planner role
   Actions: run `atelier plan` against the epic using the recording runtime,
   then inspect the launched argv/env/prompt artifact, planner AGENTS content,
   and the saved planner launch metadata
   Expected outcome: the selected profile is visible in the planner launch
   boundary and in the rendered planner template; the bounded bead contract
   includes explicit intent, non-goals, constraints, success criteria, and
   test expectations; the workspace identifier stays stable; the planner still
   runs the startup-check flow before any planning work. Source of truth:
   [Behavior and Design Notes], [Specification], and the implementation plan's
   planner contract task
   Interactions: planner session resume/fresh selection, worktree creation,
   AGENTS template rendering, Beads updates, and subprocess launch

4. Name: `atelier plan` keeps resume and fresh-session behavior unchanged when
   the planner runtime profile changes
   Type: regression
   Disposition: extend
   Harness: recording runtime executable plus saved planner session state
   Preconditions: a temp project with an existing planner agent bead, covering
   both a valid saved session id and a stale saved session scenario
   Actions: run `atelier plan --runtime-profile trycycle-bounded` in the saved
   session case, the stale-session case, and with `--new-session`
   Expected outcome: the planner still resumes when it should, falls back to a
   fresh session when the saved session is stale, and honors `--new-session`
   exactly as before; changing the runtime profile does not alter shared
   workspace identity or session identity. Source of truth: the current planner
   session contract in code and the implementation plan's requirement to keep
   shared workspace identifiers stable
   Interactions: session discovery, Beads description updates, and planner
   teardown bookkeeping

5. Name: `atelier work --runtime-profile trycycle-bounded` preserves stable
   workspace identity while activating bounded worker orchestration
   Type: scenario
   Disposition: new
   Harness: recording runtime executable plus a seeded worker/worktree scenario
   Preconditions: a runnable epic with at least one ready changeset, a project
   worktree mapping, and the bounded runtime profile selected for the worker
   role
   Actions: run `atelier work --run-mode once` with the bounded profile, then
   inspect the launched argv/env/prompt artifact, worker AGENTS content, Beads
   claim updates, and worktree metadata
   Expected outcome: the worker launch boundary records the selected runtime
   profile; the worker template reflects the bounded profile contract; the
   project and workspace identifiers stay stable across the session; and the
   worker still performs the standard claim, worktree, and teardown flow under
   Atelier semantics. Source of truth: [Worker Runtime Architecture],
   [Specification], and the implementation plan's worker runtime profile task
   Interactions: worktree creation, Beads ownership updates, agent home setup,
   runtime env sanitization, and subprocess launch

6. Name: bounded worker runtime fails closed when convergence cannot be proven
   Type: boundary
   Disposition: new
   Harness: recording runtime executable configured to emit malformed or absent
   helper-session evidence
   Preconditions: the worker profile is `trycycle-bounded`, and the fixture is
   set to return a non-zero exit, a missing session id, or incomplete
   convergence evidence
   Actions: run `atelier work --run-mode once` against a runnable changeset
   using the failing fixture
   Expected outcome: the changeset is marked blocked or fail-closed with
   explicit evidence, the worker does not finalize or integrate the changeset,
   and no silent scope expansion or identity churn occurs. Source of truth:
   the user-approved requirement that an acceptable outcome is to fail closed
   when trycycle cannot be adapted safely, plus the worker plan's fail-closed
   guardrail
   Interactions: retry handling, teardown, Beads description updates, and
   finalization gates

7. Name: bounded and standard worker profiles produce the same Atelier end
   state for the same runnable changeset
   Type: differential
   Disposition: new
   Harness: recording runtime executable plus a repeated seeded worker scenario
   Preconditions: the same runnable changeset state is prepared twice, once
   with `runtime.worker.profile=standard` and once with
   `runtime.worker.profile=trycycle-bounded`
   Actions: run `atelier work --run-mode once` under each profile, then compare
   the resulting Beads state, worktree mapping, branch mapping, and teardown
   artifacts
   Expected outcome: the core Atelier end state matches between profiles where
   invariants are supposed to hold, and the only differences are bounded-profile
   metadata and evidence fields. Source of truth: the implementation plan's
   "default behavior stays intact" guardrail and the docs' existing worker
   contract
   Interactions: worker orchestration, Beads persistence, branch mapping, and
   runtime cleanup

8. Name: planner and worker templates surface the runtime profile and bounded
   contract expectations
   Type: regression
   Disposition: extend
   Harness: template snapshot tests
   Preconditions: the updated `AGENTS.planner.md.tmpl` and
   `AGENTS.worker.md.tmpl` files are present in the source tree
   Actions: read the template files directly and assert the runtime profile
   fields and bounded-loop guidance are rendered in the expected sections
   Expected outcome: both templates mention the selected runtime profile, the
   planner template explains the stricter bead contract, and the worker
   template explains the bounded worker loop, nested helper-session boundary,
   and fail-closed behavior. Source of truth: the implementation plan's
   planner and worker contract tasks
   Interactions: template rendering context and downstream agent bootstrap

## Coverage summary

This plan covers the user-visible action space that the implementation plan
touches: `atelier config` prompt/edit round-trips, `atelier plan` and
`atelier work` runtime-profile flags, config model validation, planner and
worker AGENTS rendering, Beads/worktree side effects, resume/fresh behavior,
and fail-closed worker outcomes.

The plan explicitly excludes a real external trycycle binary smoke test, manual
visual review, and broader GitHub/PR integration behavior. Those exclusions
keep the cost aligned with the approved bounded-profile implementation, but
they leave residual risk that a future real trycycle runtime may differ from
the recording fixture even when Atelier's subprocess contract remains correct.

If the bounded profile later grows into a true external trycycle dependency,
add one opt-in smoke test against the real binary before treating parity as
complete.

<!-- inline reference link definitions. please keep alphabetized -->

[behavior and design notes]: ../behavior.md
[specification]: ../SPEC.md
[worker runtime architecture]: ../worker-runtime-architecture.md
