from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from atelier import exec as exec_util
from atelier.lib.beads import (
    Beads,
    BeadsCapability,
    BeadsCommandResult,
    CloseIssueRequest,
    CreateIssueRequest,
    IssueRecord,
    ListIssuesRequest,
    ReadyIssuesRequest,
    ShowIssueRequest,
    SupportedOperation,
    SyncBeadsClient,
    UpdateIssueRequest,
    decode_help_output,
    decode_version_output,
)
from atelier.testing.beads import (
    DEFAULT_PRIME_FULL_OUTPUT,
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
    SUPPORTED_GLOBAL_FLAGS,
    CommandEnvelope,
    InMemoryBeadsBackend,
    InMemoryBeadsClient,
    InMemoryBeadsCommandBackend,
    InMemoryBeadsDispatcher,
    InMemoryStartupAdminBackend,
    InMemoryStartupAdminState,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
    build_in_memory_issue_store,
    build_startup_admin_fixture,
    normalize_invocation,
)
from atelier.testing.beads.core_issues import InMemoryCoreIssuesHandler

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "in-memory-beads-command-contract.md"
CLIENT_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"


def test_contract_docs_publish_route_inventory() -> None:
    content = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    client_contract = CLIENT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "In-Memory Beads Command Contract" in content
    assert "source contract" in content
    assert IN_MEMORY_BEADS_VERSION in content
    assert "- `core-issues` (Tier 0): routes `show`, `list`, `ready`, `create`," in content
    assert "- `runtime-admin` (Tier 3): routes `stats`, `doctor`, `migrate`," in content
    assert "`--json` routes: all documented routes" in content
    assert "`--json` routes: `dolt show`," in content
    assert "`vc status`" in content
    assert "build_in_memory_beads_client()" in content
    assert "backed directly by the in-memory store" in content
    assert "Intentional Tier 0 Deltas" in content
    assert "dep add" in content
    assert "dep remove" in content
    assert "build_startup_admin_fixture" in content
    assert "No emulation of real Dolt storage internals" in content
    for flag in SUPPORTED_GLOBAL_FLAGS:
        assert flag in content
    for route in DOCUMENTED_COMMAND_ROUTES:
        assert route.command_label in content
        assert route.family_id in content
    assert "docs/in-memory-beads-command-contract.md" in client_contract


def test_documented_routes_cover_each_planned_command_family() -> None:
    assert {route.family_id for route in DOCUMENTED_COMMAND_ROUTES} == {
        "core-issues",
        "dependency-edges",
        "ownership-slots",
        "startup-config",
        "runtime-admin",
    }


def test_dispatcher_protocol_and_version_help_are_client_compatible() -> None:
    dispatcher = InMemoryBeadsDispatcher()

    assert isinstance(dispatcher, InMemoryBeadsCommandBackend)

    version_result = dispatcher.run(["bd", "--version"])
    help_result = dispatcher.run(["bd", "show", "--help"])

    assert str(decode_version_output(version_result)) == IN_MEMORY_BEADS_VERSION
    normalized_help = BeadsCommandResult(
        argv=tuple(str(token) for token in help_result.args),
        returncode=help_result.returncode,
        stdout=help_result.stdout,
        stderr=help_result.stderr,
    )
    assert decode_help_output(normalized_help).supports_json_output is True


def test_dispatcher_strips_supported_global_flags_before_matching() -> None:
    builder = IssueFixtureBuilder()

    def core_handler(route, invocation):  # type: ignore[no-untyped-def]
        del invocation
        assert route.command == ("show",)
        return CommandEnvelope.json_payload([builder.issue(7)])

    dispatcher = InMemoryBeadsDispatcher(family_handlers={"core-issues": core_handler})
    result = dispatcher.run(["bd", "--db", "/tmp/beads.db", "--readonly", "show", "at-7", "--json"])

    issue = IssueRecord.model_validate(json.loads(result.stdout)[0])

    assert issue.id == "at-7"


@pytest.mark.parametrize(
    ("argv", "family_id"),
    [
        (["bd", "show", "at-1", "--json"], "core-issues"),
        (["bd", "dep", "add", "at-2", "at-1", "--json"], "dependency-edges"),
        (["bd", "slot", "set", "at-agent", "hook", "at-epic"], "ownership-slots"),
        (["bd", "config", "set", "issue_prefix", "at"], "startup-config"),
        (["bd", "dolt", "commit"], "runtime-admin"),
    ],
)
def test_dispatcher_marks_default_family_handlers_as_explicitly_unimplemented(
    argv: list[str],
    family_id: str,
) -> None:
    result = InMemoryBeadsDispatcher().run(argv)

    assert result.returncode == DEFAULT_UNIMPLEMENTED_RETURN_CODE
    assert family_id in result.stderr
    assert "not implemented yet" in result.stderr


def test_issue_fixture_builder_is_deterministic_and_payload_compatible() -> None:
    builder = IssueFixtureBuilder()
    first = builder.issue(
        5,
        labels=("atelier", "changeset", "atelier"),
        parent=1,
        dependencies=(2,),
        metadata={"claimed_by": "agent-1"},
        extra_fields={"future_field": {"nested": True}},
    )

    assert first == builder.issue(
        5,
        labels=("atelier", "changeset", "atelier"),
        parent=1,
        dependencies=(2,),
        metadata={"claimed_by": "agent-1"},
        extra_fields={"future_field": {"nested": True}},
    )

    issue = IssueRecord.model_validate(first)

    assert issue.id == "at-5"
    assert issue.labels == ("atelier", "changeset")
    assert issue.parent and issue.parent.id == "at-1"
    assert issue.dependencies[0].id == "at-2"
    assert issue.extra_fields["future_field"] == {"nested": True}


def test_normalize_invocation_preserves_command_and_global_tokens() -> None:
    invocation = normalize_invocation(
        ["bd", "--db=/tmp/beads.db", "--sandbox", "vc", "status", "--json"]
    )

    assert invocation.global_tokens == ("--db=/tmp/beads.db", "--sandbox")
    assert invocation.command_tokens == ("vc", "status", "--json")
    assert invocation.requests_json is True


def test_dispatcher_implements_tier_zero_core_issue_commands() -> None:
    builder = IssueFixtureBuilder()
    store = build_in_memory_issue_store(
        issues=(
            builder.issue(
                1,
                title="Epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
            builder.issue(2, title="Base slice", parent=1, status="open"),
            builder.issue(3, title="Follow-up slice", parent=1, status="open", dependencies=(2,)),
            builder.issue(4, title="Closed slice", parent=1, status="closed"),
        )
    )
    dispatcher = InMemoryBeadsDispatcher(
        family_handlers={"core-issues": InMemoryCoreIssuesHandler(store)}
    )

    listed = dispatcher.run(["bd", "list", "--parent", "at-1", "--limit", "2", "--json"])
    ready_before = dispatcher.run(["bd", "ready", "--parent", "at-1", "--json"])
    created = dispatcher.run(
        [
            "bd",
            "create",
            "--title",
            "New slice",
            "--type",
            "task",
            "--parent",
            "at-1",
            "--labels",
            "tier0,worker",
            "--json",
        ]
    )

    created_issue = IssueRecord.model_validate(json.loads(created.stdout)[0])
    updated = dispatcher.run(
        [
            "bd",
            "update",
            created_issue.id,
            "--status",
            "in_progress",
            "--set-labels",
            "worker",
            "--set-labels",
            "in-flight",
            "--json",
        ]
    )
    merged = dispatcher.run(
        [
            "bd",
            "update",
            "at-2",
            "--set-labels",
            "cs:merged",
            "--json",
        ]
    )
    shown = dispatcher.run(["bd", "show", created_issue.id, "--json"])
    closed = dispatcher.run(["bd", "close", "at-2", "--reason", "done", "--json"])
    ready_after = dispatcher.run(["bd", "ready", "--parent", "at-1", "--json"])

    listed_ids = [item["id"] for item in json.loads(listed.stdout)]
    ready_before_ids = [item["id"] for item in json.loads(ready_before.stdout)]
    updated_issue = IssueRecord.model_validate(json.loads(updated.stdout)[0])
    merged_issue = IssueRecord.model_validate(json.loads(merged.stdout)[0])
    shown_issue = IssueRecord.model_validate(json.loads(shown.stdout)[0])
    closed_issue = IssueRecord.model_validate(json.loads(closed.stdout)[0])
    ready_after_ids = [item["id"] for item in json.loads(ready_after.stdout)]

    assert listed_ids == ["at-2", "at-3"]
    assert ready_before_ids == ["at-2"]
    assert created_issue.parent and created_issue.parent.id == "at-1"
    assert created_issue.labels == ("tier0", "worker")
    assert updated_issue.status == "in_progress"
    assert updated_issue.labels == ("worker", "in-flight")
    assert merged_issue.labels == ("cs:merged",)
    assert shown_issue.id == created_issue.id
    assert closed_issue.status == "closed"
    assert ready_after_ids == ["at-3", created_issue.id]


def test_in_memory_client_supports_representative_planner_flow() -> None:
    builder = IssueFixtureBuilder()
    client, _store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                1,
                title="Epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
            builder.issue(2, title="Base slice", parent=1, status="open"),
            builder.issue(
                3,
                title="Follow-up slice",
                parent=1,
                status="open",
                dependencies=(2,),
                labels=("review",),
            ),
            builder.issue(4, title="Closed slice", parent=1, status="closed"),
        )
    )
    sync = SyncBeadsClient(client)

    assert isinstance(client, Beads)

    environment = sync.inspect_environment()
    listed = sync.list(ListIssuesRequest(parent_id="at-1"))
    filtered = sync.list(
        ListIssuesRequest(parent_id="at-1", title_query="follow", labels=("review",))
    )
    ready_before = sync.ready(ReadyIssuesRequest(parent_id="at-1"))
    sync.close(CloseIssueRequest(issue_id="at-2"))
    ready_after = sync.ready(ReadyIssuesRequest(parent_id="at-1"))
    sync.update(
        UpdateIssueRequest(
            issue_id="at-2",
            labels=("cs:merged",),
        )
    )
    ready_after_merge = sync.ready(ReadyIssuesRequest(parent_id="at-1"))
    listed_all = sync.list(ListIssuesRequest(parent_id="at-1", include_closed=True))

    assert str(environment.version) == IN_MEMORY_BEADS_VERSION
    assert {
        BeadsCapability.VERSION_REPORTING,
        BeadsCapability.ISSUE_JSON,
        BeadsCapability.ISSUE_MUTATION,
        BeadsCapability.READY_DISCOVERY,
    }.issubset(set(environment.capabilities))
    assert [issue.id for issue in listed] == ["at-2", "at-3"]
    assert [issue.id for issue in filtered] == ["at-3"]
    assert [issue.id for issue in ready_before] == ["at-2"]
    assert [issue.id for issue in ready_after] == []
    assert [issue.id for issue in ready_after_merge] == ["at-3"]
    assert [issue.id for issue in listed_all] == ["at-2", "at-3", "at-4"]


def test_typed_client_mutates_the_store_directly() -> None:
    builder = IssueFixtureBuilder()
    client, store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                1,
                title="Epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
        )
    )
    sync = SyncBeadsClient(client)

    assert isinstance(client, InMemoryBeadsClient)

    created = sync.create(CreateIssueRequest(title="Shared slice", type="task", parent_id="at-1"))
    shown = IssueRecord.model_validate(store.show(created.id))
    store.close(created.id, reason="done")
    closed = sync.show(ShowIssueRequest(issue_id=created.id))

    assert shown.id == created.id
    assert shown.parent and shown.parent.id == "at-1"
    assert closed.status == "closed"


def test_ready_requires_integrated_evidence_for_closed_changeset_dependencies() -> None:
    builder = IssueFixtureBuilder()
    client, _store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                1,
                title="Epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
            builder.issue(2, title="Base slice", parent=1, status="closed"),
            builder.issue(3, title="Follow-up slice", parent=1, status="open", dependencies=(2,)),
            builder.issue(
                4,
                title="Merged slice",
                parent=1,
                status="closed",
                description="pr_state: merged",
            ),
            builder.issue(5, title="Merged follow-up", parent=1, status="open", dependencies=(4,)),
        )
    )
    sync = SyncBeadsClient(client)

    ready = sync.ready(ReadyIssuesRequest(parent_id="at-1"))

    assert [issue.id for issue in ready] == ["at-5"]


def test_in_memory_client_supports_representative_worker_flow() -> None:
    builder = IssueFixtureBuilder()
    client, store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                1,
                title="Epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
        )
    )
    sync = SyncBeadsClient(client)

    created = sync.create(
        CreateIssueRequest(
            title="Implement Tier 0",
            type="task",
            parent_id="at-1",
            description="Add in-memory commands.",
            labels=("worker", "worker"),
        )
    )
    shown = sync.show(ShowIssueRequest(issue_id=created.id))
    updated = sync.update(
        UpdateIssueRequest(
            issue_id=created.id,
            status="in_progress",
            labels=("worker", "tier0"),
        )
    )
    closed = sync.close(CloseIssueRequest(issue_id=created.id, reason="done"))
    children = sync.list(ListIssuesRequest(parent_id="at-1", include_closed=True))
    parent = IssueRecord.model_validate(store.show("at-1"))

    assert created.id == "at-2"
    assert shown.parent and shown.parent.id == "at-1"
    assert updated.status == "in_progress"
    assert updated.labels == ("worker", "tier0")
    assert closed.status == "closed"
    assert [issue.id for issue in children] == ["at-2"]
    assert [child.id for child in parent.children] == ["at-2"]


def test_in_memory_tier_zero_policy_tracks_only_implemented_operations() -> None:
    assert {
        contract.operation for contract in IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY.operations
    } == {
        SupportedOperation.INSPECT_ENVIRONMENT,
        SupportedOperation.SHOW,
        SupportedOperation.LIST,
        SupportedOperation.READY,
        SupportedOperation.CREATE,
        SupportedOperation.UPDATE,
        SupportedOperation.CLOSE,
    }


def test_stateful_backend_round_trips_hook_slots() -> None:
    builder = IssueFixtureBuilder()
    backend = InMemoryBeadsBackend(
        seeded_issues=(builder.issue("at-agent", issue_type="agent", labels=("at:agent",)),)
    )

    backend.run(["bd", "slot", "set", "at-agent", "hook", "at-epic"])
    show_result = backend.run(["bd", "slot", "show", "at-agent", "--json"])

    assert json.loads(show_result.stdout) == {"slots": {"hook": "at-epic"}}

    backend.run(["bd", "slot", "clear", "at-agent", "hook"])
    cleared_result = backend.run(["bd", "slot", "show", "at-agent", "--json"])

    assert json.loads(cleared_result.stdout) == {"slots": {}}


def test_stateful_backend_fails_closed_when_claim_owner_differs() -> None:
    builder = IssueFixtureBuilder()
    backend = InMemoryBeadsBackend(
        seeded_issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic",),
                assignee="agent-a",
            ),
        )
    )

    result = backend.run(["bd", "--actor", "agent-b", "update", "at-epic", "--claim", "--json"])

    assert result.returncode == 1
    assert "already has an assignee" in result.stderr
    assert backend.state.show("at-epic")["assignee"] == "agent-a"


def test_stateful_backend_allows_only_one_concurrent_claim_winner() -> None:
    builder = IssueFixtureBuilder()
    backend = InMemoryBeadsBackend(
        seeded_issues=(builder.issue("at-epic", issue_type="epic", labels=("at:epic",)),)
    )
    barrier = threading.Barrier(2)
    winners: list[str] = []
    failures: list[str] = []

    def claim(actor: str) -> None:
        barrier.wait(timeout=1.0)
        result = backend.run(["bd", "--actor", actor, "update", "at-epic", "--claim", "--json"])
        if result.returncode == 0:
            winners.append(json.loads(result.stdout)[0]["assignee"])
        else:
            failures.append(result.stderr)

    first = threading.Thread(target=claim, args=("agent-a",))
    second = threading.Thread(target=claim, args=("agent-b",))
    first.start()
    second.start()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(winners) == 1
    assert len(failures) == 1
    assert backend.state.show("at-epic")["assignee"] == winners[0]


def test_startup_admin_backend_config_types_and_rename_round_trip() -> None:
    state = InMemoryStartupAdminState(
        issue_prefix="old",
        custom_types=("agent",),
        rename_pending_count=2,
    )
    backend = InMemoryStartupAdminBackend(state=state)

    config_before = backend.run(["bd", "config", "get", "issue_prefix", "--json"])
    types_before = backend.run(["bd", "types", "--json"])
    rename_preview = backend.run(["bd", "rename-prefix", "new-", "--repair", "--dry-run"])
    rename_apply = backend.run(["bd", "rename-prefix", "new-", "--repair"])
    config_after = backend.run(["bd", "config", "get", "issue_prefix", "--json"])

    assert json.loads(config_before.stdout)["value"] == "old"
    assert json.loads(types_before.stdout)["custom_types"] == [{"name": "agent"}]
    assert "Would rename 2 issues from prefix 'old' to 'new'" in rename_preview.stdout
    assert "Renamed 2 issues from prefix 'old' to 'new'" in rename_apply.stdout
    assert json.loads(config_after.stdout)["value"] == "new"


def test_startup_admin_backend_runtime_admin_routes_update_state(tmp_path: Path) -> None:
    fixture = build_startup_admin_fixture(
        tmp_path=tmp_path,
        has_dolt_store=False,
        legacy_issue_total=8,
        dolt_issue_totals=(2,),
        dolt_auto_commit="batch",
        vc_status_payload={"working_set": {"tables": ["issues"]}},
    )
    backend = fixture.backend

    stats_active = backend.run(["bd", "stats", "--json"])
    stats_legacy = backend.run(
        ["bd", "--db", str(fixture.beads_root / "beads.db"), "stats", "--json"]
    )
    inspect_migrate = backend.run(
        [
            "bd",
            "--db",
            str(fixture.beads_root / "beads.db"),
            "migrate",
            "--to-dolt",
            "--inspect",
            "--json",
        ]
    )
    apply_migrate = backend.run(
        [
            "bd",
            "--db",
            str(fixture.beads_root / "beads.db"),
            "migrate",
            "--to-dolt",
            "--yes",
            "--json",
        ]
    )
    dolt_show = backend.run(["bd", "dolt", "show", "--json"])
    set_database = backend.run(["bd", "dolt", "set", "database", "beads_ops", "--update-config"])
    vc_status = backend.run(["bd", "vc", "status", "--json"])

    assert json.loads(stats_active.stdout)["summary"]["total_issues"] == 2
    assert json.loads(stats_legacy.stdout)["summary"]["total_issues"] == 8
    assert json.loads(inspect_migrate.stdout) == {"inspect": "ok"}
    assert json.loads(apply_migrate.stdout) == {"migrated": 8}
    assert (fixture.beads_root / "dolt" / "beads_at" / ".dolt").is_dir()
    assert json.loads(dolt_show.stdout)["database"] == "beads_at"
    assert set_database.returncode == 0
    assert fixture.state.dolt_database == "beads_ops"
    assert json.loads(vc_status.stdout)["working_set"]["tables"] == ["issues"]


def test_startup_admin_fixture_runner_adapts_to_exec_requests(tmp_path: Path) -> None:
    fixture = build_startup_admin_fixture(
        tmp_path=tmp_path,
        has_dolt_store=True,
        legacy_issue_total=4,
        dolt_issue_totals=(4,),
        dolt_auto_commit="batch",
        vc_status_payload={"working_set": {"tables": ["issues"]}},
        prime_full_output=DEFAULT_PRIME_FULL_OUTPUT,
    )

    result = fixture.runner.run(
        exec_util.CommandRequest(
            argv=("bd", "prime", "--full"),
            cwd=fixture.repo_root,
            env={},
        )
    )

    assert result is not None
    assert "bd dolt commit" in result.stdout
    assert result.returncode == 0
