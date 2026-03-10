# Beads Adoption Guide

This guide records the current adoption boundary for `atelier.lib.beads` and
`atelier.testing.beads`. It is intentionally narrow. The goal is to use the new
Beads APIs where they pay off today without turning them into an accidental
store abstraction before `at-njpt4` lands.

## Decision Rule

Use `atelier.lib.beads` directly when all of the following are true:

- The code is a low-level adapter or helper that already owns Beads transport
  concerns such as `BEADS_DIR`, repo cwd, or `--readonly` wiring.
- The code benefits from typed request/response models more than it benefits
  from a higher-level Atelier-owned store interface.
- The seam is still close to raw issue semantics, not planner/worker business
  policy.

Use `atelier.testing.beads` when the code under test already depends on
`atelier.lib.beads` and the test only needs Beads semantics, not a real `bd`
subprocess.

Wait for `at-njpt4` when the work wants to define or consume an Atelier-owned
store concept rather than a low-level Beads boundary.

## Where Direct Client Use Is In Bounds Today

- Boundary helpers that would otherwise build raw `bd` argv directly.
- Adapters that import or export Beads issues and only need typed issue
  semantics.
- Low-level GC helpers that read or mutate Beads issues near the subprocess
  boundary.
- Tests around those adopted low-level seams that need realistic Beads issue
  payloads but not real CLI transport.

## Where Direct Client Use Is Out Of Bounds

- Planner or worker orchestration services that coordinate lifecycle, review,
  publish, or dependency policy.
- New helper layers that aggregate multiple Beads operations into an
  Atelier-specific store API.
- Business-logic modules that only want derived decisions and should not know
  about `BEADS_DIR`, cwd, raw Beads ids, or subprocess capabilities.
- Test suites that must prove shell wiring, `bd --help` probing, publish
  scripts, or other subprocess-specific behavior.

## Test Backend Choice

Prefer `atelier.testing.beads` for:

- shared typed-client contract coverage
- low-level semantic tests that seed issue payloads directly
- planner or worker tests only after the production seam under test already uses
  `atelier.lib.beads`

Keep real-`bd` coverage explicit for:

- shell tests
- command-integration tests that verify subprocess wiring
- planner or worker suites whose production path still shells out through legacy
  helpers
- publish flows
- version/help probing
- dependency mutation coverage until the in-memory backend grows that semantic

## Anti-Guidance

Do not:

- parse `bd` stdout in new low-level helpers when `atelier.lib.beads` already
  covers the operation
- spread direct `Beads` construction upward into planner or worker policy code
- convert `IssueRecord` values back into loose dicts immediately just to match
  legacy call shapes
- use broad CLI monkeypatching in tests when `atelier.testing.beads` can model
  the same issue semantics deterministically
- treat the current client surface as a permanent substitute for the
  higher-level store abstraction planned in `at-njpt4`

## Lessons From The Adoption Slices

### Keep Typed Records Typed

The low-level adoption work was cleaner when helpers kept `IssueRecord` values
through their seam. Converting typed responses back into dicts too early hid
contract drift and recreated the parsing/normalization work the shared client
already owns.

### Own Client Construction At The Boundary

The adopted helpers became easier to reason about once the caller that already
owned `beads_root`, repo cwd, and readonly intent also owned
`build_sync_beads_client(...)`. That kept transport concerns explicit and made
tests patch a single construction seam instead of several thin wrappers.

### Use Semantic Startup State, Not Raw Probes

`inspect_startup_state()` is the right shared boundary for startup readiness.
Callers should depend on semantic readiness, migration, and operator-attention
signals rather than raw `bd stats` output, Dolt marker layouts, or probe
provenance.

### Default The Adopted Beads Boundary To The In-Memory Backend

Once a test exercises code that already depends on `atelier.lib.beads`, moving
that suite onto `atelier.testing.beads` removes `bd` binary and store-coupling
noise without losing meaningful coverage. The remaining real-`bd` tests are the
ones that still need to prove subprocess wiring, publish behavior, or
higher-level planner/worker paths that have not crossed that boundary yet.

### Surface Contract Gaps Explicitly

The migration exposed real gaps cleanly:

- the in-memory backend still lacks dependency mutation semantics
- typed mutation requests must preserve legitimate edge cases such as clearing
  an assignee instead of assuming every optional field is truthy-only
- direct client use still needs a future Atelier-owned store layer above it

## Follow-On Work

- `at-njpt4` should define the Atelier-owned store abstraction for planner and
  worker business logic so direct `Beads` usage stays limited to boundary code.
- Extend `atelier.testing.beads` with dependency mutation semantics when a test
  truly needs them; until then keep those assertions in explicit subprocess
  coverage.
- Keep future direct-client adoption review-sized. If a change starts moving
  planner/worker policy onto `Beads`, split or defer it instead of expanding the
  low-level boundary.
