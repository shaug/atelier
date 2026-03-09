## In-memory Beads Testing Guide

`atelier.testing.beads` is the default backend for planner and worker
unit-service tests. Use the real `bd` CLI only when the test must verify an
external integration boundary.

### Backend Selection Rule

- Use `atelier.testing.beads` for planner startup, worker startup, selection,
  and finalization logic that only depends on Beads semantics.
- Keep real-`bd` coverage for shell and command-integration tests that must
  prove subprocess wiring, repository bootstrap behavior, or publish scripts.
- Fail closed when a test needs a Beads semantic the in-memory backend does not
  implement yet. Extend the backend contract instead of reintroducing ad hoc CLI
  monkeypatching.

### Current Migration Boundary

The following planner-worker suites now run against the in-memory backend by
default:

- `tests/atelier/test_planner_startup_check.py`
- `tests/atelier/worker/test_changeset_state.py`
- `tests/atelier/worker/test_work_startup_runtime.py`

Additional targeted worker-session coverage now uses the in-memory backend for
Beads semantics:

- `tests/atelier/worker/test_session_worktree.py`
  `prepare_worktrees()` metadata and workspace-parent alignment cases seed
  issues through `atelier.testing.beads`, while targeted failure injection stays
  local to the specific `bd show` call under test.

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

The `prepare_worktrees()` migration exposed one deliberate seam:
`atelier.testing.beads` virtualizes Beads semantics, not the surrounding
filesystem. Tests still need explicit temp directories, mapping files, and
`.git` markers when worktree orchestration logic reads local state. Keep that
split explicit instead of broadening the Beads harness into a fake worktree
runtime.

### Runtime And Reliability Impact

Measured on March 9, 2026 with warm `pytest` runs on CPython 3.11.12:

- Baseline committed suite before this migration: `23` tests in `0.470s`
- Current migrated suite after this changeset: `25` tests in `0.474s`

The warm runtime stayed effectively flat while adding two backend-backed tests.
The practical gain is reliability: these planner-worker suites no longer depend
on a local `bd` binary, Dolt state, or CLI monkeypatch scaffolding to exercise
startup and lifecycle behavior.
