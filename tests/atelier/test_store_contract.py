from __future__ import annotations

from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest
from pydantic import ValidationError

import atelier.store as public_store
from atelier.lib.beads import Beads, RecordingBeadsTransport, SubprocessBeadsClient
from atelier.store import (
    AtelierStore,
    ChangesetBranches,
    ChangesetQuery,
    ChangesetRecord,
    ClaimMessageRequest,
    ClearHookRequest,
    CreateMessageRequest,
    DependencyMutation,
    DependencyRecord,
    EpicQuery,
    EpicRecord,
    HookRecord,
    LifecycleStatus,
    LifecycleTransition,
    LifecycleTransitionRequest,
    MessageDelivery,
    MessageQuery,
    MessageRecord,
    MessageThreadKind,
    ReadyChangesetQuery,
    ReviewMetadata,
    ReviewState,
    SetHookRequest,
    UpdateReviewRequest,
    WorkItemKind,
    WorkRef,
)
from atelier.testing.beads import build_in_memory_beads_client

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
BEADS_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"
ADOPTION_GUIDE_PATH = REPO_ROOT / "docs" / "beads-adoption-guide.md"

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
