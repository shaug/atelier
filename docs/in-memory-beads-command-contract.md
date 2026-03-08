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

| Family id | Tier | Routes | `--json` routes | | --- | --- | --- | --- | |
`core-issues` | Tier 0 | `show`, `list`, `ready`, `create`, `update`, `close` |
all | | `dependency-edges` | Tier 0 | `dep add`, `dep remove` | all | |
`ownership-slots` | Tier 1 | `slot show`, `slot set`, `slot clear` | `slot show`
| | `startup-config` | Tier 2 | `prime`, `init`, `config get`, `config set`,
`types`, `rename-prefix` | `config get`, `types` | | `runtime-admin` | Tier 3 |
`stats`, `doctor`, `migrate`, `dolt show`, `dolt set database`, `dolt commit`,
`vc status` | `dolt show`, `vc status` |

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

## Non-Goals

- No production runtime wiring in this slice
- No silent approximation of unsupported command semantics
- No parallel public API outside `atelier.testing.beads`
- No attempt to reimplement the full `bd` CLI before command-family changesets
  land

## Proof Artifacts

- `src/atelier/testing/beads/contract.py`
- `src/atelier/testing/beads/dispatcher.py`
- `src/atelier/testing/beads/fixtures.py`
- `tests/atelier/testing/fixtures/in_memory_beads_command_contract_v1.json`
- `tests/atelier/testing/test_in_memory_beads.py`
