from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest
from pydantic import ValidationError

import atelier.store as public_store
from atelier.lib.beads import (
    Beads,
    BeadsCommandResult,
    RecordingBeadsTransport,
    ScriptedBeadsTransport,
    SubprocessBeadsClient,
    UnsupportedOperationError,
)
from atelier.messages import render_message
from atelier.store import (
    AtelierStore,
    ChangesetBranches,
    ChangesetRecord,
    ClaimMessageRequest,
    ClearHookRequest,
    CreateMessageRequest,
    DependencyMutation,
    DependencyRecord,
    EpicRecord,
    HookRecord,
    LifecycleStatus,
    LifecycleTransitionRequest,
    MessageDelivery,
    MessageQuery,
    MessageRecord,
    MessageThreadKind,
    ReviewMetadata,
    ReviewState,
    SetHookRequest,
    UpdateReviewRequest,
    WorkItemKind,
    WorkRef,
    build_atelier_store,
)
from atelier.testing.beads import IssueFixtureBuilder, build_in_memory_beads_client

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
BEADS_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"
ADOPTION_GUIDE_PATH = REPO_ROOT / "docs" / "beads-adoption-guide.md"
BUILDER = IssueFixtureBuilder()
_RUN = asyncio.run
_HELP = "Flags:\n  -h, --help   help for command\n      --json  Output in JSON format"

_STORE_METHOD_NAMES = (
    "get_epic",
    "list_epics",
    "get_changeset",
    "list_changesets",
    "list_ready_changesets",
    "list_messages",
    "get_agent_hook",
    "add_dependency",
    "remove_dependency",
    "create_message",
    "claim_message",
    "set_agent_hook",
    "clear_agent_hook",
    "update_review",
    "transition_lifecycle",
)


def _annotation_leaks_beads_contract(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is not None:
        return _annotation_leaks_beads_contract(origin) or any(
            _annotation_leaks_beads_contract(arg) for arg in get_args(annotation)
        )
    return annotation is Beads or getattr(annotation, "__module__", "").startswith(
        "atelier.lib.beads"
    )


def test_changeset_record_captures_store_owned_metadata() -> None:
    record = ChangesetRecord(
        id="at-123",
        title="Implement store contract",
        lifecycle=LifecycleStatus.IN_PROGRESS,
        epic_id="at-epic",
        labels=("atelier", "store", "atelier"),
        dependencies=(
            DependencyRecord(
                issue_id="at-123",
                depends_on_id="at-122",
                satisfied=False,
            ),
        ),
        branches=ChangesetBranches(
            root_branch="root/store",
            parent_branch="main",
            work_branch="root/store-at-123",
        ),
        review=ReviewMetadata(
            pr_number=17,
            pr_state=ReviewState.IN_REVIEW,
            review_owner="scott",
            integrated_sha="abc1234",
        ),
    )

    assert record.labels == ("atelier", "store")
    assert record.review.pr_number == 17
    assert record.review.pr_state is ReviewState.IN_REVIEW
    assert record.branches and record.branches.work_branch == "root/store-at-123"


def test_work_threaded_messages_require_thread_identity() -> None:
    with pytest.raises(ValidationError, match="thread_id"):
        CreateMessageRequest(title="Need a decision")

    with pytest.raises(ValidationError, match="thread_kind"):
        CreateMessageRequest(title="Need a decision", thread_id="at-123")

    request = CreateMessageRequest(
        title="Need a decision",
        body="Choose one of the migration paths.",
        thread_id="at-123",
        thread_kind=MessageThreadKind.CHANGESET,
        audience=("planner", "planner"),
    )

    assert request.audience == ("planner",)


def test_store_message_query_and_request_do_not_expose_assignee_routing() -> None:
    assert "assignee" not in MessageQuery.model_fields
    assert "assignee" not in CreateMessageRequest.model_fields


def test_message_record_enforces_store_message_contract() -> None:
    record = MessageRecord(
        id="msg-1",
        title="Need a decision",
        delivery=MessageDelivery.WORK_THREADED,
        status=LifecycleStatus.OPEN,
        thread_id="at-123",
        thread_kind=MessageThreadKind.CHANGESET,
        audience=("worker", "planner", "worker"),
    )

    assert record.audience == ("worker", "planner")


def test_store_message_contract_only_exposes_durable_threaded_path() -> None:
    assert tuple(item.value for item in MessageDelivery) == ("work-threaded",)
    assert tuple(item.value for item in MessageThreadKind) == ("changeset", "epic")


def test_store_contract_stays_above_the_beads_client_layer() -> None:
    process_backend = SubprocessBeadsClient(
        transport=RecordingBeadsTransport(),
        cwd=Path("."),
        beads_root=Path("."),
        env={},
    )
    in_memory_client, _ = build_in_memory_beads_client()

    assert isinstance(process_backend, Beads)
    assert isinstance(in_memory_client, Beads)
    assert not isinstance(process_backend, AtelierStore)
    assert not isinstance(in_memory_client, AtelierStore)

    for method_name in _STORE_METHOD_NAMES:
        hints = get_type_hints(getattr(AtelierStore, method_name))
        assert hints, method_name
        assert not any(
            _annotation_leaks_beads_contract(annotation) for annotation in hints.values()
        ), method_name


def test_public_store_is_concrete_beads_backed_type() -> None:
    in_memory_client, _ = build_in_memory_beads_client()

    store = AtelierStore(beads=in_memory_client)

    assert isinstance(store, AtelierStore)


def test_public_store_module_exports_single_store_surface() -> None:
    assert "AsyncAtelierStore" not in public_store.__all__
    assert not hasattr(public_store, "AsyncAtelierStore")


def test_store_contract_docs_record_invariants_and_deferred_work() -> None:
    store_doc = STORE_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    beads_doc = BEADS_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    adoption_guide = ADOPTION_GUIDE_PATH.read_text(encoding="utf-8")

    assert "Atelier Store Contract" in store_doc
    assert "Atelier-Owned Invariants" in store_doc
    assert "Beads-Client Responsibilities" in store_doc
    assert "Deferred Work" in store_doc
    assert "single async store boundary" in store_doc
    assert "not part of `atelier.store`" in store_doc
    assert "adapter-local compatibility state" in store_doc
    assert "implement `AtelierStore` itself" in store_doc
    assert "`atelier.lib.beads.Beads` remains the swappable boundary" in store_doc
    assert "implementing `AtelierStore` graph and discovery methods" in store_doc
    assert "GitHub issue #644" in store_doc
    assert "GitHub issue #645" in store_doc
    assert "GitHub issue #646" in store_doc
    assert "[Atelier Store Contract]" in beads_doc
    assert "[Atelier Store Contract]" in adoption_guide


def test_epic_and_work_refs_are_store_native_models() -> None:
    epic = EpicRecord(
        id="at-epic",
        title="Epic",
        lifecycle=LifecycleStatus.OPEN,
        changesets=(WorkRef(id="at-1", title="One", kind=WorkItemKind.CHANGESET),),
    )

    assert epic.kind is WorkItemKind.EPIC
    assert epic.changesets[0].kind is WorkItemKind.CHANGESET


def _store_for(*issues: dict[str, object]):
    client, _ = build_in_memory_beads_client(issues=issues)
    return build_atelier_store(beads=client)


def _ok(*argv: str, stdout: str = "") -> BeadsCommandResult:
    return BeadsCommandResult(argv=argv, returncode=0, stdout=stdout)


def _issue_json(**payload: object) -> str:
    return json.dumps([payload], separators=(",", ":"))


def _queue_message(
    *, claimed_by: str | None = None, assignee: str | None = None
) -> dict[str, object]:
    metadata = {
        "delivery": "work-threaded",
        "thread": "at-change",
        "thread_kind": "changeset",
        "queue": "planner",
        "audience": ["planner"],
    }
    if claimed_by is not None:
        metadata["claimed_by"] = claimed_by
    return BUILDER.issue(
        "msg-queue",
        labels=("at:message", "at:unread"),
        assignee=assignee,
        description=render_message(metadata, "Need a decision."),
    )


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_beads_store_mutation_paths(operation: str) -> None:
    store = _store_for(
        BUILDER.issue("at-epic", issue_type="epic", labels=("at:epic",)),
        BUILDER.issue(
            "at-change",
            parent="at-epic",
            description=(
                "pr_url: https://example.invalid/pr/41\n"
                "pr_number: 41\n"
                "pr_state: draft-pr\n"
                "review_owner: reviewer-a\n"
            ),
        ),
        BUILDER.issue(
            "at-agent",
            title="atelier/worker/agent",
            issue_type="agent",
            labels=("at:agent",),
            description="agent_id: atelier/worker/agent\nhook_bead: null\n",
        ),
        _queue_message(),
    )
    review = _RUN(
        store.update_review(
            UpdateReviewRequest(
                changeset_id="at-change",
                review=ReviewMetadata(
                    pr_state=ReviewState.IN_REVIEW,
                    review_owner="reviewer-b",
                    integrated_sha="abc1234",
                ),
                preserve_existing=True,
            )
        )
    )

    assert (review.review.pr_url, review.review.pr_number, review.review.integrated_sha) == (
        "https://example.invalid/pr/41",
        41,
        "abc1234",
    )
    assert (
        _RUN(
            store.transition_lifecycle(
                LifecycleTransitionRequest(
                    issue_id="at-change",
                    target_status=LifecycleStatus.IN_PROGRESS,
                    expected_current=LifecycleStatus.OPEN,
                )
            )
        ).to_status
        is LifecycleStatus.IN_PROGRESS
    )
    assert (
        _RUN(
            store.create_message(
                CreateMessageRequest(
                    title="NEEDS-DECISION: pick one",
                    body="Choose one migration path.",
                    sender="atelier/worker/codex/p100",
                    thread_id="at-change",
                    thread_kind=MessageThreadKind.CHANGESET,
                    audience=("planner",),
                    queue="planner",
                    kind="needs-decision",
                    blocking=True,
                )
            )
        ).queue
        == "planner"
    )
    assert (
        _RUN(
            store.claim_message(
                ClaimMessageRequest(
                    message_id="msg-queue",
                    claimed_by="atelier/planner/codex/p200",
                )
            )
        ).claimed_by
        == "atelier/planner/codex/p200"
    )
    assert (
        _RUN(
            store.set_agent_hook(SetHookRequest(agent_id="atelier/worker/agent", epic_id="at-epic"))
        ).epic_id
        == "at-epic"
    )
    assert _RUN(
        store.clear_agent_hook(
            ClearHookRequest(agent_id="atelier/worker/agent", expected_epic_id="at-epic")
        )
    ) == HookRecord(agent_id="atelier/worker/agent", epic_id="at-epic")

    probe = {
        ("bd", "--version"): _ok("bd", "--version", stdout="bd version 0.56.1 (dev)"),
        ("bd", "show", "--help"): _ok("bd", "show", "--help", stdout=_HELP),
        ("bd", "list", "--help"): _ok("bd", "list", "--help", stdout=_HELP),
        ("bd", "create", "--help"): _ok("bd", "create", "--help", stdout=_HELP),
        ("bd", "update", "--help"): _ok("bd", "update", "--help", stdout=_HELP),
        ("bd", "close", "--help"): _ok("bd", "close", "--help", stdout=_HELP),
        ("bd", "dep", "add", "--help"): _ok("bd", "dep", "add", "--help", stdout=_HELP),
        ("bd", "dep", "remove", "--help"): _ok("bd", "dep", "remove", "--help", stdout=_HELP),
        ("bd", "ready", "--help"): _ok("bd", "ready", "--help", stdout=_HELP),
        ("bd", "list", "--json", "--parent", "at-change", "--all", "--limit", "10000"): _ok(
            "bd",
            "list",
            "--json",
            "--parent",
            "at-change",
            "--all",
            "--limit",
            "10000",
            stdout="[]",
        ),
        ("bd", "list", "--json", "--parent", "at-dep", "--all", "--limit", "10000"): _ok(
            "bd",
            "list",
            "--json",
            "--parent",
            "at-dep",
            "--all",
            "--limit",
            "10000",
            stdout="[]",
        ),
        ("bd", "show", "at-change", "--json"): (
            _ok(
                "bd",
                "show",
                "at-change",
                "--json",
                stdout=_issue_json(
                    id="at-change",
                    issue_type="task",
                    **({"dependencies": ["at-dep"]} if operation == "remove" else {}),
                ),
            ),
            _ok(
                "bd",
                "show",
                "at-change",
                "--json",
                stdout=_issue_json(
                    id="at-change",
                    issue_type="task",
                    **({"dependencies": ["at-dep"]} if operation == "add" else {}),
                ),
            ),
        ),
        ("bd", "show", "at-dep", "--json"): (
            _ok(
                "bd",
                "show",
                "at-dep",
                "--json",
                stdout=_issue_json(
                    id="at-dep",
                    issue_type="task",
                    status="closed",
                    description="pr_state: merged\n",
                ),
            ),
            _ok(
                "bd",
                "show",
                "at-dep",
                "--json",
                stdout=_issue_json(
                    id="at-dep",
                    issue_type="task",
                    status="closed",
                    description="pr_state: merged\n",
                ),
            ),
        ),
        ("bd", "dep", operation, "at-change", "at-dep", "--json"): _ok(
            "bd",
            "dep",
            operation,
            "at-change",
            "at-dep",
            "--json",
            stdout=json.dumps(
                {
                    "issue_id": "at-change",
                    "depends_on_id": "at-dep",
                    "status": operation,
                },
                separators=(",", ":"),
            ),
        ),
    }
    dep_store = build_atelier_store(
        beads=SubprocessBeadsClient(transport=ScriptedBeadsTransport(probe))
    )
    mutation = DependencyMutation(issue_id="at-change", depends_on_id="at-dep")
    result = _RUN(
        dep_store.add_dependency(mutation)
        if operation == "add"
        else dep_store.remove_dependency(mutation)
    )

    assert result is not None and (result.issue_id, result.depends_on_id, result.satisfied) == (
        "at-change",
        "at-dep",
        True,
    )


def test_beads_store_fails_closed() -> None:
    store = _store_for(
        BUILDER.issue("at-epic", issue_type="epic", labels=("at:epic",)),
        BUILDER.issue("at-change", parent="at-epic", status="blocked"),
        BUILDER.issue("at-dep", status="closed", description="pr_state: merged\n"),
        _queue_message(
            claimed_by="atelier/planner/codex/p999",
            assignee="atelier/planner/codex/p999",
        ),
    )

    with pytest.raises(ValueError, match="already claimed"):
        _RUN(
            store.claim_message(
                ClaimMessageRequest(
                    message_id="msg-queue",
                    claimed_by="atelier/planner/codex/p200",
                )
            )
        )
    with pytest.raises(ValueError, match="lifecycle mismatch"):
        _RUN(
            store.transition_lifecycle(
                LifecycleTransitionRequest(
                    issue_id="at-change",
                    target_status=LifecycleStatus.IN_PROGRESS,
                    expected_current=LifecycleStatus.OPEN,
                )
            )
        )
    with pytest.raises(UnsupportedOperationError, match="dep-add"):
        _RUN(store.add_dependency(DependencyMutation(issue_id="at-change", depends_on_id="at-dep")))
