## In-memory Beads Testing Guide

`atelier.testing.beads` is the default backend for tests that exercise code
already written against `atelier.lib.beads`. Use the real `bd` CLI when the test
must verify an external integration boundary or production code that still
crosses the legacy subprocess seam directly.

For the broader boundary between direct `atelier.lib.beads` adoption, test-only
adoption, and work that should wait for `at-njpt4`, see
[`docs/beads-adoption-guide.md`](docs/beads-adoption-guide.md).

### Backend Selection Rule

- Use `atelier.testing.beads` when the code under test already depends on
  `atelier.lib.beads` and the assertions only need Beads semantics.
- Keep real-`bd` coverage for shell and command-integration tests that must
  prove subprocess wiring, repository bootstrap behavior, or publish scripts.
- Keep real-`bd` coverage for planner/worker suites whose production path has
  not adopted the shared Beads client yet.
- Fail closed when a test needs a Beads semantic the in-memory backend does not
  implement yet. Extend the backend contract instead of reintroducing ad hoc CLI
  monkeypatching.

### Current Migration Boundary

The following suites are the current adopted exceptions because their code under
test already crosses the shared Beads boundary:

- `tests/atelier/test_planner_startup_check.py`
- `tests/atelier/worker/test_changeset_state.py`
- `tests/atelier/worker/test_work_startup_runtime.py`

The shared client-contract suite also defaults to the in-memory backend for Tier
0 Beads semantics, while keeping subprocess-specific assertions explicit:

- `tests/atelier/lib/test_beads.py` Shared
  `show`/`list`/`ready`/`create`/`update`/`close` coverage now runs against
  `build_in_memory_beads_client(...)`, while help/version probing, timeouts, and
  dependency mutation remain process-backed tests by exception.

Keep real-`bd` integration coverage explicit in suites such as:

- `tests/shell/publish_scripts_test.sh`
- `tests/shell/run.sh`
- `tests/atelier/commands/test_init.py`

### Pattern For New Tests

Seed the backend with realistic issue payloads, then patch `atelier.beads`
through the shared command runner:

```python
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    patch_in_memory_beads,
)

builder = IssueFixtureBuilder()
backend = InMemoryBeadsBackend(
    seeded_issues=(
        builder.issue("at-epic", issue_type="epic", labels=("at:epic",)),
        builder.issue("at-epic.1", parent="at-epic", status="open"),
    )
)

with patch_in_memory_beads(backend):
    ...
```

Use `IssueFixtureBuilder` for deterministic Beads payloads and
`messages.render_message(...)` when a test needs queue or threaded-message
frontmatter.

When a test needs startup classification semantics, prefer the typed client:

```python
from atelier.lib.beads import BeadsStartupState, SyncBeadsClient
from atelier.testing.beads import build_in_memory_beads_client

client, _store = build_in_memory_beads_client(
    startup_state=BeadsStartupState(
        classification="ready",
        migration_eligible=False,
        active_backend_ready=True,
        operator_attention_required=False,
        reason="backend_ready",
        backend="dolt",
    )
)

startup = SyncBeadsClient(client).inspect_startup_state()
```

Keep typed-client startup assertions focused on semantic readiness, migration,
and operator-attention signals. Raw counts and probe provenance belong only in
compatibility fixture tests.

Reserve `build_startup_admin_fixture(...)` for compatibility tests that need to
assert raw `bd stats`, `migrate`, or `dolt show` command behavior.

### Fixture Ergonomics Note

The shared-client migration exposed one current Tier 0 gap:
`build_in_memory_beads_client(...)` does not implement dependency mutation yet.
Keep `dep add` and `dep remove` assertions in explicit subprocess tests until
the in-memory contract grows that semantic, instead of falling back to broad CLI
monkeypatching for the whole module.

The same migration also reinforced a boundary rule: if a test only needs issue
semantics, seed the in-memory backend only after the code under test already
depends on `atelier.lib.beads`, then keep the suite local. Do not take that as
permission to move higher-level planner or worker policy modules directly onto
`Beads`; that layer still belongs to `at-njpt4`.

### Runtime And Reliability Impact

Measured on March 9, 2026 with warm `pytest` runs on CPython 3.11.12:

- Baseline committed suite before this migration: `23` tests in `0.470s`
- Current migrated suite after this changeset: `25` tests in `0.474s`

The warm runtime stayed effectively flat while adding two backend-backed tests.
The practical gain is reliability: these planner-worker suites no longer depend
on a local `bd` binary, Dolt state, or CLI monkeypatch scaffolding to exercise
startup and lifecycle behavior.
