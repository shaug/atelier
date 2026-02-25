# Atelier Service Tier Proposal

## Summary

Introduce a lightweight service/use-case tier for workflows that orchestrate
multiple side effects (CLI prompts, config writes, Beads mutations, git/PR
operations). Keep pure data and utility helpers outside this tier.

The target is better orchestration clarity, explicit result/error contracts, and
easier testing at command/runtime boundaries without introducing a heavy
framework.

## Inspiration and alignment

This proposal is inspired by Ruby ServiceActor: https://github.com/sunny/actor

Shared intent:

- one entrypoint per use-case orchestration unit
- explicit contracts for success/failure behavior
- composable workflow building blocks

Important Atelier differences (Python-first):

- Default implementation is class-first service modules with one public
  `<Verb><Domain>Service.run(...)` entrypoint.
- External inputs are validated with typed request/context models at service
  boundaries, preferring Pydantic where data crosses CLI/process/provider
  boundaries.
- Pure in-process orchestration can use dataclasses/typed models without
  macro-style DSL behavior.
- Expected failures raise `ServiceFailure` (extends Exception); services extend
  `BaseService` which catches it and invokes a configurable handler (default
  re-raises; callers decide interface-specific behavior).

## Why now

Current Atelier code already has strong typed boundaries in many places, but
side-effect orchestration logic is still split across command modules and
runtime helper facades. This makes some flows harder to reason about and test as
end-to-end units.

A bounded service tier gives us:

- one entrypoint per workflow use-case
- explicit success/failure contracts
- thinner command/runtime controllers
- deterministic test seams for orchestration behavior

## Goals

- Define a concrete service/use-case layer shape for Atelier.
- Map current modules into candidate service boundaries.
- Standardize result and error contracts for side-effect-heavy flows.
- Pilot the pattern on a narrow path before broader refactors.

## Non-goals

- Rewriting all helpers into services.
- Introducing a generic service framework or DSL.
- Replacing existing typed ports/protocols already working well.
- Changing user-facing CLI behavior as part of proposal adoption.

## Proposed layer model

Use three practical layers:

1. `Command/Runtime Controllers`
1. `Service / Use-case Tier`
1. `Domain + Adapters`

### 1) Command/Runtime controllers

Keep controllers thin:

- parse/normalize CLI/runtime input
- call exactly one primary use-case entrypoint
- render output and exit behavior

Examples:

- `src/atelier/commands/init.py`
- `src/atelier/commands/work.py`
- `src/atelier/worker/session/runner.py`

### 2) Service / use-case tier

Create one module per orchestrated workflow. These modules own sequencing,
policy checks, and error mapping.

Naming conventions:

- Module path: `src/atelier/services/<domain>/<use_case>.py`
- Default entrypoint: `<Verb><Domain>Service.run(...)`
- Exception: function-first entrypoint is allowed only for tiny, single-sequence
  services with no injected collaborators; name must be
  `<domain>_<verb>_service(...)`.
- Request models end with `Context` or `Request`.
- Success payload models end with `Outcome`.
- Errors use stable string codes (see contracts section).

### 3) Domain + adapters

Keep pure logic and boundary integrations separate:

- domain helpers stay in existing modules where no orchestration state is needed
- adapters remain in typed port/boundary modules (`exec`, `worker/ports`,
  `models_boundary`, provider adapters)

## Service composition rules

Keep composition explicit and bounded:

- Default guideline: keep composition depth to at most three service hops in one
  request path.
- Exception path: if a workflow temporarily needs deeper composition, document
  rationale plus an exit plan in the service module docstring and link the
  tracking issue/changeset.
- Parent services may call child services only through typed request/result
  contracts.
- Child services that raise `ServiceFailure` propagate unchanged unless
  intentionally remapped at one boundary layer with rationale in code
  comments/docstring.
- No hidden side effects: all external writes/commands must run through explicit
  adapter dependencies.
- Service modules must avoid mutable global state and implicit singleton caches.

### Dependency injection contract

Service collaborators must be explicit and testable:

- Pass long-lived collaborators (ports, adapters, policy evaluators) through
  constructors or explicit dependency bundles.
- Pass per-request values (paths, runtime mode, correlation ids) through typed
  request/context objects.
- Do not resolve collaborators via module-level singleton lookups inside service
  methods.
- Tests must inject fakes through the same constructor/request seams used in
  production.

## Candidate module mapping

This mapping defines where current code should move as services are adopted.

1. Current: `src/atelier/commands/init.py` Role: end-to-end init orchestration
   (prompts, provider selection, Beads setup, optional policy sync) Candidate:
   `services/project/initialize_project.py`
1. Current: `src/atelier/config.py` (`build_project_config`) Role: config
   prompt/merge and normalization Candidate:
   `services/project/compose_project_config.py` (or `project_config_service`)
1. Current: `src/atelier/external_registry.py` (`resolve_planner_provider`)
   Role: provider candidate selection and ranking Candidate:
   `services/project/resolve_external_provider.py`
1. Current: `src/atelier/worker/prompts.py` (`worker_opening_prompt`) and
   `src/atelier/worker/work_startup_runtime.py` prompt path Role: worker opening
   prompt composition with mode-specific guidance Candidate:
   `services/worker/compose_opening_prompt.py`
1. Current: `src/atelier/worker/session/startup.py` and
   `src/atelier/worker/work_startup_runtime.py` Role: startup contract
   sequencing and changeset selection Candidate:
   `services/worker/run_startup_contract.py`
1. Current: `src/atelier/worker/work_finalization_pipeline.py` plus finalization
   modules Role: finalize/publish orchestration and transitions Candidate:
   `services/worker/finalize_changeset.py`

## Init/config prompting pilot boundary

The first refactor target should be the `init` + config prompt assembly path.

Current boundary spread:

- CLI controller: `src/atelier/commands/init.py`
- Prompt/merge logic: `src/atelier/config.py::build_project_config`
- Provider resolution: `src/atelier/external_registry.py`
- Side-effect boundaries: config writes, Beads setup, policy bead sync

Pilot boundary after extraction:

- `InitializeProjectService` owns full orchestration sequence.
- `ComposeProjectConfigService` returns typed config outcomes.
- `ResolveExternalProviderService` returns ranked candidates and selected
  provider.
- `commands/init.py` becomes controller + output rendering only.

## Worker orchestration mapping

Worker runtime already has typed models and ports; service extraction should
wrap orchestration units, not replace those contracts.

Near-term candidate services:

- `RunStartupContractService`
  - wraps startup selection flow now split between `worker/session/runner.py`,
    `worker/session/startup.py`, and `worker/work_startup_runtime.py`
- `ComposeWorkerOpeningPromptService`
  - wraps prompt assembly and mode-specific policy text
- `FinalizeChangesetService`
  - wraps finalization/publish decision orchestration while preserving existing
    pipeline helpers

## Result and error contracts

Services return typed outcomes on success and raise `ServiceFailure` on expected
domain/policy/runtime failures. Callers catch `ServiceFailure` and handle per
their interface (e.g., CLI dies, web returns 4xx/5xx, native app shows dialog).

Validation rule:

- Every service entrypoint uses typed `Request`/`Context` models as first-tier
  validation before business orchestration starts.
- Validation failures must raise `ServiceFailure("validation_failed", ...)` with
  a stable message and optional recovery hint.
- Use Pydantic models for untrusted/external boundaries, then operate on typed
  dataclasses/validated models internally.
- Add explicit constraint checks when types alone cannot express requirements
  (for example numeric bounds, path safety, or string format invariants); raise
  `ServiceFailure("validation_failed", ...)` for these cases.

Failure handling rule:

- Raise `ServiceFailure` for expected domain/policy/runtime failures that
  callers can handle deterministically.
- At service boundaries, catch non-`ServiceFailure` dependency exceptions and
  map them to stable failure categories:
  - map `OSError` to `IoFailedError`
  - map command/process exits to `ExternalCommandFailedError`
  - map other unexpected dependency failures to `UnexpectedStateError`
  - use `raise ... from exc` to preserve causal tracebacks
- Raise normal exceptions for programmer bugs or invariant violations that
  indicate a defect requiring code changes.

```python
from abc import ABC, abstractmethod
from typing import Generic, Literal, TypeVar

R = TypeVar("R")
T = TypeVar("T")

ServiceFailureCode = Literal[
    "validation_failed",
    "dependency_missing",
    "policy_blocked",
    "external_command_failed",
    "io_failed",
    "unexpected_state",
]


class ServiceFailure(Exception):
    """Expected service failure. Raised by services; callers catch and handle."""

    def __init__(
        self,
        code: ServiceFailureCode,
        message: str,
        *,
        recovery_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recovery_hint = recovery_hint


# Convenience subclasses (omit code; use ``raise ValidationFailedError("msg")``)
class ValidationFailedError(ServiceFailure): ...
class DependencyMissingError(ServiceFailure): ...
class PolicyBlockedError(ServiceFailure): ...
class ExternalCommandFailedError(ServiceFailure): ...
class IoFailedError(ServiceFailure): ...
class UnexpectedStateError(ServiceFailure): ...


class BaseService(ABC, Generic[R, T]):
    """Abstract base. Subclasses implement _run(request) -> T."""

    def __call__(self, request: R) -> T:
        try:
            return self._run(request)
        except ServiceFailure as e:
            return self._handle_failure(e)

    @abstractmethod
    def _run(self, request: R) -> T:
        """Execute service logic. Raise ServiceFailure on expected errors."""
        ...

    def _handle_failure(self, error: ServiceFailure) -> T:
        """Handle ServiceFailure. Default re-raises; override for recovery."""
        raise
```

### Contract example: init/config orchestration

`InitializeProjectService` returns:

- success outcome
  - config path written
  - selected provider
  - beads root initialized
  - optional policy sync performed
- failure codes
  - `validation_failed` for invalid config/editor input
  - `dependency_missing` for unavailable agent tooling
  - `io_failed` for config write / store setup errors

### Golden path example (controller to service)

```python
def run_init_controller(argv: list[str], deps: InitControllerDeps) -> int:
    request = parse_init_request(argv)
    service_request = InitializeProjectRequest(...)

    try:
        outcome = deps.initialize_project_service.run(service_request)
        render_init_success(outcome)
        return 0
    except ServiceFailure as e:
        hint = f"\nHint: {e.recovery_hint}" if e.recovery_hint else ""
        die(f"init failed ({e.code}): {e}{hint}")
```

The caller catches `ServiceFailure` and handles per its interface. CLI calls
`die()`; web would return 4xx/5xx; tests use `pytest.raises(ServiceFailure)`.

### Contract example: worker finalization orchestration

`FinalizeChangesetService` returns:

- success outcome
  - lifecycle action taken (`pushed`, `pr-open`, `merged`, etc.)
  - resulting refs/PR URL when available
- failure codes
  - `policy_blocked` when PR strategy gates creation
  - `external_command_failed` when git/gh commands fail
  - `unexpected_state` for inconsistent changeset metadata

## Adoption guardrails

Apply the service tier when all are true:

- flow spans multiple side effects
- flow has policy gates or lifecycle transitions
- flow benefits from stable success/error outcomes

Service vs helper decision checklist:

- Does this flow coordinate two or more side-effect boundaries?
- Does it enforce policy gates or lifecycle transitions?
- Does caller behavior depend on stable failure codes?
- Does it orchestrate multiple adapters/ports in sequence?

If two or more checklist answers are yes, prefer a service entrypoint over a
helper extraction.

Do not apply when any are true:

- function is pure transformation/formatting
- behavior is a thin adapter around one existing typed boundary call
- extraction would only add forwarding layers with no contract improvement

## Migration anti-goals

- Do not create one-class-per-function wrappers.
- Do not move stable pure helpers into service modules.
- Do not redesign public CLI contracts during this refactor.
- Do not run broad cross-module renames before pilot metrics are reviewed.

## Pilot implementation plan

### Phase CS1: proposal and contracts (this changeset)

Deliverables:

- this proposal document
- module mapping and guardrails
- typed result/error contract examples

Exit criteria:

- maintainers agree on service naming and boundary model
- pilot path is explicitly scoped before code movement

### Phase CS2: bounded init/config prompt refactor

Deliverables:

- extract `InitializeProjectService` and config composition service boundary
- keep `commands/init.py` thin and behavior-compatible
- add focused tests around service success/failure contracts

Service test levels rubric:

- Service unit tests:
  - inject fakes for adapters/ports and assert orchestration sequence; use
    `pytest.raises(ServiceFailure)` for failure paths.
- Request/response contract tests:
  - validate typed request parsing, constraint failures, and stable error codes.
- Command-level integration tests:
  - exercise `atelier init` controller wiring to confirm render/exit behavior
    remains compatible when the service is introduced.

Exit criteria:

- no user-visible behavior regression in `atelier init`
- service-level tests cover key failure paths
- command module shrinks to controller responsibilities

### Phase CS3: evaluate and decide expansion

Deliverables:

- compare pilot complexity/testability before vs after
- decide whether to extend pattern to worker startup and/or finalization

Exit criteria:

- written decision record for expand/adjust/stop
- if expanding, define next bounded changeset per workflow

## Success metrics for pilot review

- lower orchestration complexity in command/runtime entry modules
- clearer failure reporting from typed service result contracts
- easier unit testing of orchestration without shelling full CLI sessions
- baseline observability at service entrypoints: structured
  start/success/failure logs plus duration measurement
- no broad helper churn outside declared pilot boundary
