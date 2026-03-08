from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
    SUPPORTED_GLOBAL_FLAGS,
    CommandEnvelope,
    InMemoryBeadsCommandBackend,
    InMemoryBeadsDispatcher,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
    build_in_memory_dispatcher,
    build_in_memory_issue_store,
    normalize_invocation,
)

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
    assert "Intentional Tier 0 Deltas" in content
    assert "dep add" in content
    assert "dep remove" in content
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
    dispatcher = build_in_memory_dispatcher(issue_store=store)

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
