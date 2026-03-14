from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from atelier.lib.beads import RecordingBeadsTransport, SubprocessBeadsClient
from atelier.store import (
    AtelierStore,
    ChangesetBranches,
    ChangesetRecord,
    CreateMessageRequest,
    DependencyRecord,
    EpicRecord,
    LifecycleStatus,
    MessageDelivery,
    MessageRecord,
    MessageThreadKind,
    ReviewMetadata,
    ReviewState,
    WorkItemKind,
    WorkRef,
)
from atelier.testing.beads import build_in_memory_beads_client

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
BEADS_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"
ADOPTION_GUIDE_PATH = REPO_ROOT / "docs" / "beads-adoption-guide.md"


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


def test_store_service_is_backend_neutral_and_fail_closed() -> None:
    process_backed = AtelierStore(
        SubprocessBeadsClient(
            transport=RecordingBeadsTransport(),
            cwd=Path("."),
            beads_root=Path("."),
            env={},
        )
    )
    in_memory_client, _store = build_in_memory_beads_client()
    in_memory = AtelierStore(in_memory_client)

    assert process_backed.beads_backend is not None
    assert in_memory.beads_backend is in_memory_client

    with pytest.raises(
        NotImplementedError,
        match="AtelierStore.get_epic is deferred to the follow-on store adapter changesets",
    ):
        asyncio.run(process_backed.get_epic("at-epic"))


def test_store_contract_docs_record_invariants_and_deferred_work() -> None:
    store_doc = STORE_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    beads_doc = BEADS_CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    adoption_guide = ADOPTION_GUIDE_PATH.read_text(encoding="utf-8")

    assert "Atelier Store Contract" in store_doc
    assert "Atelier-Owned Invariants" in store_doc
    assert "Beads-Client Responsibilities" in store_doc
    assert "Deferred Work" in store_doc
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
