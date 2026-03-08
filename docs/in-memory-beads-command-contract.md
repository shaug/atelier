# In-Memory Beads Command Contract

This document publishes the command-dispatch contract for the in-memory Beads
backend introduced for `at-s1vc`.

It is intentionally lower level than `docs/beads-client-contract.md`. The client
contract describes the typed `atelier.lib.beads` API. This document describes
the test-only command harness that later `at-s1vc.*` changesets plug semantic
behavior into so existing Atelier runtime flows can be exercised without
shelling out to a real `bd` process.

This file is the source contract for the `atelier.testing.beads` dispatcher and
fixture harness. Subsequent in-memory implementation changesets must update this
document first when they add, remove, or reinterpret command families.

## Execution Contract

- Entry point: `InMemoryBeadsCommandBackend.run(argv, *, cwd=None, env=None)`
- Input shape: argv-style command tokens, with or without a leading `bd`
  executable token
- Output shape: `subprocess.CompletedProcess[str]`-compatible result with
  deterministic `args`, `returncode`, `stdout`, and `stderr`
- Emulated version string: `bd version 0.56.1 (in-memory)`
- Default unsupported semantic result: exit code `2` with an explicit
  `not implemented yet` stderr marker

The dispatcher strips these leading global flags before route matching:

- `--actor`
- `--allow-stale`
- `--db`
- `--dolt-auto-commit`
- `--profile`
- `--quiet`
- `--readonly`
- `--sandbox`
- `--verbose`

`--help` is handled centrally for every documented route. `--json` is treated as
part of the published contract only for the routes listed below.

## Documented Command Families

The harness recognizes the following route families. Later changesets add real
semantics behind these routes without changing the public dispatcher boundary.

- `core-issues` (Tier 0): routes `show`, `list`, `ready`, `create`, `update`,
  `close`; `--json` routes: all documented routes
- `dependency-edges` (Tier 0): routes `dep add`, `dep remove`; `--json` routes:
  all documented routes
- `ownership-slots` (Tier 1): routes `slot show`, `slot set`, `slot clear`;
  `--json` routes: `slot show`
- `startup-config` (Tier 2): routes `prime`, `init`, `config get`, `config set`,
  `types`, `rename-prefix`; `--json` routes: `config get`, `types`
- `runtime-admin` (Tier 3): routes `stats`, `doctor`, `migrate`, `dolt show`,
  `dolt set database`, `dolt commit`, `vc status`; `--json` routes: `dolt show`,
  `vc status`

Notes:

- Tier 1 ownership conflict semantics are layered behavior implemented by later
  changesets on top of issue mutation plus slot operations; this slice only
  freezes the slot command routes.
- `config get` covers current runtime probes such as `issue_prefix`,
  `types.custom`, and `dolt.auto-commit`.
- `config set` covers current runtime writes such as `issue_prefix`,
  `types.custom`, and `beads.role`.
- The dispatcher publishes parseable help output for each documented route even
  before that route has real stateful behavior.

## Fixture Contract

`atelier.testing.beads.IssueFixtureBuilder` provides deterministic payload
builders for canonical issue envelopes.

- Canonical integer ids use the `at-<n>` namespace by default.
- Fixture timestamps are stable and derived from the issue number when possible.
- Labels are deduplicated while preserving order.
- Common Beads fields are emitted in the same JSON-friendly shape used by the
  typed client contract: `id`, `title`, `issue_type`, `status`, `labels`,
  `parent`, `dependencies`, `children`, `metadata`, plus any explicit extras.

These builders are intentionally payload-oriented. They do not implement
persistence or command semantics by themselves.

## Tier 0 Semantic Notes

This changeset wires real Tier 0 stateful semantics behind the `core-issues`
family and exposes them through a typed in-memory client adapter in
`atelier.testing.beads`.

- `build_in_memory_beads_client()` returns the shared `atelier.lib.beads.Beads`
  protocol backed by the in-memory dispatcher.
- The dispatcher is not a second semantic backend. It is the stable
  command-contract seam from `at-s1vc.1`, and the typed client intentionally
  wraps that same dispatcher/store so argv-level parity tests and direct
  protocol tests exercise one source of truth.
- The default in-memory compatibility policy currently validates only the
  implemented Tier 0 operations: `show`, `list`, `ready`, `create`, `update`,
  and `close`, even though `inspect_environment()` still reports help-probed
  capabilities for later documented routes.
- `list` supports the filtering forms used by current Atelier callsites:
  `--parent`, `--status`, `--assignee`, `--title-contains`, repeated `--label`,
  `--all`, and `--limit`.
- `ready` uses Atelier's shared lifecycle helpers: runnable results must be leaf
  work beads, have active lifecycle status, and have all dependencies in a
  satisfied terminal state. Closed changeset dependencies still require stored
  integration evidence such as `pr_state: merged` or the `cs:merged` label,
  matching worker startup's default dependency gate.
- `create`, `update`, and `close` preserve parent/child and dependency
  relationships so higher-level planner/worker assertions can observe stable
  graph behavior across mutations.

## Intentional Tier 0 Deltas

- Dependency mutation commands (`dep add`, `dep remove`) remain documented but
  intentionally unimplemented in this slice; later changesets add their real
  semantics.
- The in-memory command handler only accepts the argv shapes covered by the v1
  typed client plus the documented Tier 0 filters above. Non-contract flags such
  as `--silent`, `--body-file`, `--add-label`, and `--remove-label` fail closed
  instead of approximating subprocess-specific behavior.
- Dependency readiness does not emulate live integration probes. Tier 0 only
  honors stored integration evidence already present on the dependency issue,
  such as `pr_state: merged` or `cs:merged`; it does not synthesize merge proof
  from git state or verify `changeset.integrated_sha`.

## Non-Goals

- No production runtime wiring in this slice
- No silent approximation of unsupported command semantics
- No parallel public API outside `atelier.testing.beads`
- No attempt to reimplement the full `bd` CLI before command-family changesets
  land

## Proof Artifacts

- `src/atelier/testing/beads/contract.py`
- `src/atelier/testing/beads/client.py`
- `src/atelier/testing/beads/core_issues.py`
- `src/atelier/testing/beads/dispatcher.py`
- `src/atelier/testing/beads/fixtures.py`
- `src/atelier/testing/beads/store.py`
- `tests/atelier/testing/test_in_memory_beads.py`
