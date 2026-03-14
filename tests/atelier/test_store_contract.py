from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from atelier.lib.beads import RecordingBeadsTransport, SubprocessBeadsClient
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


class _StoreAdapterStub(AtelierStore):
    def __init__(self, backend: object) -> None:
        self.backend = backend

    async def get_epic(self, epic_id: str) -> EpicRecord:
        return EpicRecord(id=epic_id, title="Epic", lifecycle=LifecycleStatus.OPEN)

    async def list_epics(self, query: EpicQuery = EpicQuery()) -> tuple[EpicRecord, ...]:
        del query
        return (EpicRecord(id="at-epic", title="Epic", lifecycle=LifecycleStatus.OPEN),)

    async def get_changeset(self, changeset_id: str) -> ChangesetRecord:
        return ChangesetRecord(
            id=changeset_id,
            title="Changeset",
            lifecycle=LifecycleStatus.OPEN,
        )

    async def list_changesets(
        self,
        query: ChangesetQuery = ChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        del query
        return (
            ChangesetRecord(
                id="at-1",
                title="Changeset",
                lifecycle=LifecycleStatus.OPEN,
            ),
        )

    async def list_ready_changesets(
        self,
        query: ReadyChangesetQuery = ReadyChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        del query
        return ()

    async def list_messages(
        self, query: MessageQuery = MessageQuery()
    ) -> tuple[MessageRecord, ...]:
        del query
        return ()

    async def get_agent_hook(self, agent_id: str) -> HookRecord | None:
        return HookRecord(agent_id=agent_id, epic_id="at-epic")

    async def add_dependency(self, mutation: DependencyMutation) -> DependencyRecord:
        return DependencyRecord(
            issue_id=mutation.issue_id,
            depends_on_id=mutation.depends_on_id,
            requires_integrated_state=mutation.requires_integrated_state,
        )

    async def remove_dependency(
        self,
        mutation: DependencyMutation,
    ) -> DependencyRecord | None:
        return DependencyRecord(
            issue_id=mutation.issue_id,
            depends_on_id=mutation.depends_on_id,
            requires_integrated_state=mutation.requires_integrated_state,
        )

    async def create_message(self, request: CreateMessageRequest) -> MessageRecord:
        return MessageRecord(
            id="msg-1",
            title=request.title,
            body=request.body,
            delivery=request.delivery,
            thread_id=request.thread_id,
            thread_kind=request.thread_kind,
            audience=request.audience,
        )

    async def claim_message(self, request: ClaimMessageRequest) -> MessageRecord:
        return MessageRecord(
            id=request.message_id,
            title="Claimed",
            delivery=MessageDelivery.WORK_THREADED,
            thread_id="at-epic",
            thread_kind=MessageThreadKind.EPIC,
            claimed_by=request.claimed_by,
        )

    async def set_agent_hook(self, request: SetHookRequest) -> HookRecord:
        return HookRecord(agent_id=request.agent_id, epic_id=request.epic_id)

    async def clear_agent_hook(self, request: ClearHookRequest) -> HookRecord | None:
        if request.expected_epic_id is None:
            return None
        return HookRecord(agent_id=request.agent_id, epic_id=request.expected_epic_id)

    async def update_review(self, request: UpdateReviewRequest) -> ChangesetRecord:
        return ChangesetRecord(
            id=request.changeset_id,
            title="Changeset",
            lifecycle=LifecycleStatus.OPEN,
            review=request.review,
        )

    async def transition_lifecycle(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransition:
        return LifecycleTransition(
            issue_id=request.issue_id,
            issue_kind=WorkItemKind.CHANGESET,
            from_status=request.expected_current,
            to_status=request.target_status,
            reason=request.reason,
        )


def test_store_base_class_is_backend_neutral() -> None:
    process_backed = _StoreAdapterStub(
        SubprocessBeadsClient(
            transport=RecordingBeadsTransport(),
            cwd=Path("."),
            beads_root=Path("."),
            env={},
        )
    )
    in_memory_client, _store = build_in_memory_beads_client()
    in_memory = _StoreAdapterStub(in_memory_client)

    assert isinstance(process_backed, AtelierStore)
    assert isinstance(in_memory, AtelierStore)


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
