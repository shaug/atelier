# Beads Client v1 Contract

This document publishes the supported v1 contract for `atelier.lib.beads`. It
defines the only `bd` surface the reusable client supports today, the version
and capability bounds that gate that support, and how downstream layers are
expected to adopt the client.

## Version and Capability Policy

- Minimum supported `bd` version: `0.56.1`
- Default maximum version ceiling: none
- Capability ceilings are allowed in `atelier.lib.beads.CompatibilityPolicy`
  when upstream changes require an explicit fail-closed window.

Environments are validated through
`CompatibilityPolicy.assert_environment_supports(...)`.

- Versions below `0.56.1` raise `UnsupportedVersionError`.
- Missing required capabilities raise `CapabilityMismatchError`.
- Unsupported operations raise `UnsupportedOperationError`.

`inspect_environment()` is the only text-normalized escape hatch. It uses
`bd --version` plus `bd <command> --help` probes to detect the installed version
and supported capabilities. All other supported operations require JSON-backed
decoding and return typed models rather than raw stdout.

`inspect_startup_state()` is the shared semantic escape hatch for startup and
legacy-migration classification. It is intentionally not part of the published
raw command inventory below because callers should not depend on specific
filesystem probes, `bd stats` argv shapes, or Dolt marker layouts.

## Supported Command Inventory

The v1 client contract is intentionally narrow. The supported operations are:

| Client method | Operation id | `bd` surface | Output mode | Required
capabilities | | --- | --- | --- | --- | --- | | `inspect_environment()` |
`inspect-environment` | `bd --version` plus `--help` probes | `text-normalized`
| none | | `show()` | `show` | `bd show <issue-id> --json` | `json-required` |
`version-reporting`, `issue-json` | | `list()` | `list` | `bd list --json ...` |
`json-required` | `version-reporting`, `issue-json` | | `ready()` | `ready` |
`bd ready --json ...` | `json-required` | `version-reporting`, `issue-json`,
`ready-discovery` | | `create()` | `create` | `bd create --json ...` |
`json-required` | `version-reporting`, `issue-mutation` | | `update()` |
`update` | `bd update <issue-id> --json ...` | `json-required` |
`version-reporting`, `issue-mutation` | | `close()` | `close` |
`bd close <issue-id> --json ...` | `json-required` | `version-reporting`,
`issue-mutation` | | `add_dependency()` | `dep-add` |
`bd dep add <issue-id> <dependency-id> --json` | `json-required` |
`version-reporting`, `issue-json`, `dependency-mutation` | |
`remove_dependency()` | `dep-remove` |
`bd dep remove <issue-id> <dependency-id> --json` | `json-required` |
`version-reporting`, `issue-json`, `dependency-mutation` |

The supported capability names are:

- `version-reporting`
- `issue-json`
- `issue-mutation`
- `dependency-mutation`
- `ready-discovery`

Nearby `bd` commands are intentionally outside the v1 contract unless they are
added to the typed client surface and compatibility policy. Examples of
unsupported nearby surface area include `blocked`, `doctor`, `dolt`, `edit`,
`prime`, `stats`, and prefix-management flows.

## Semantic Boundary

The shared `Beads` protocol exposes issue semantics plus one startup semantic:

- `inspect_startup_state()` returns a typed `BeadsStartupState` describing
  whether the active backend is healthy, whether recoverable legacy data still
  needs migration, or whether startup needs operator attention. The shared model
  exposes only semantic readiness/recovery flags plus a stable reason; it does
  not publish issue totals, probe provenance, or storage-artifact details.

Boundary ownership is explicit:

- The process-backed `SubprocessBeadsClient` owns `BEADS_DIR`, repository cwd,
  runtime metadata reads, `bd stats` probing, and any filesystem/Dolt marker
  inspection needed to answer `inspect_startup_state()`.
- The in-memory backend answers `inspect_startup_state()` directly from
  configured semantic state. It does not need fake `beads.db` or `.dolt`
  artifacts for typed-client callers.
- Compatibility fixtures that emulate raw startup/admin commands remain
  test-only helpers and are not the shared client boundary.

## Downstream Adoption Rules

`atelier.lib.beads.client.Beads` is the canonical downstream dependency.
Downstream code should treat the protocol plus the shared request/response
models and typed errors as the integration boundary.

For contributor-facing adoption guidance, anti-guidance, and lessons from the
initial runtime/test migrations, see [Beads Adoption Guide].

### `at-s1vc`: alternative implementation contract

The in-memory implementation planned in `at-s1vc` should implement the same
`Beads` protocol rather than exposing a parallel API.

- The command-dispatch harness contract lives in
  `docs/in-memory-beads-command-contract.md`.
- Reuse the request/response models from `atelier.lib.beads.models`.
- Preserve the typed error semantics from `atelier.lib.beads.errors`.
- Support the same v1 operation inventory; do not add extra public methods that
  bypass the shared contract.
- Provide `inspect_environment()` results that can be validated against the same
  `CompatibilityPolicy`, even though the transport is not subprocess backed.
- Answer `inspect_startup_state()` semantically rather than recreating the
  process-backed filesystem probes in higher-level callers.

### `at-njpt4`: higher-level Atelier store contract

The Atelier-owned store abstraction planned in `at-njpt4` should build on the
reusable Beads client instead of reconstructing `bd` subprocess glue.

The published contract-definition slice now lives in [Atelier Store Contract].

- Depend on the `Beads` protocol, not directly on `SubprocessBeadsClient`.
- Consume typed `IssueRecord` and request models instead of parsing `bd` stdout
  or rebuilding argv.
- Keep raw command construction, transport, compatibility probing, and startup
  storage inspection inside `atelier.lib.beads`.
- Use `SyncBeadsClient` only at synchronous call boundaries; keep the core
  integration async-first where possible.
- Treat the current direct-client adopters as low-level boundaries only; do not
  use this contract as a substitute for the higher-level store abstraction.

## Proof Artifacts

The published v1 contract is backed by a structured fixture and tests:

- `tests/atelier/lib/fixtures/beads_client_contract_v1.json`
- `tests/atelier/lib/test_beads_contract.py`

Those tests fail when the documented inventory or version policy drifts from
`DEFAULT_COMPATIBILITY_POLICY`, and they also verify that this document and the
top-level README keep the published contract visible to downstream consumers.

<!-- inline reference link definitions. please keep alphabetized -->

[atelier store contract]: ./atelier-store-contract.md
[beads adoption guide]: ./beads-adoption-guide.md
