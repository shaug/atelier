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
    BeadsCommandRequest,
    BeadsCommandResult,
    RecordingBeadsTransport,
    ScriptedBeadsTransport,
    SubprocessBeadsClient,
    UnsupportedOperationError,
)
from atelier.messages import render_message
from atelier.store import (
    AppendNotesRequest,
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
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
BEADS_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"
ADOPTION_GUIDE_PATH = REPO_ROOT / "docs" / "beads-adoption-guide.md"
BUILDER = IssueFixtureBuilder()
_RUN = asyncio.run
_HELP = "Flags:\n  -h, --help   help for command\n      --json  Output in JSON format"
_BACKENDS = ("in-memory", "subprocess")

_STORE_METHOD_NAMES = (
    "get_epic",
    "list_epics",
    "epic_discovery_parity",
    "get_changeset",
    "list_changesets",
    "list_ready_changesets",
    "list_messages",
    "get_agent_hook",
    "add_dependency",
    "remove_dependency",
    "create_message",
    "append_notes",
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


def test_append_notes_request_requires_non_empty_deduped_notes() -> None:
    with pytest.raises(ValidationError, match="append notes requires at least one non-empty note"):
        AppendNotesRequest(issue_id="at-123", notes=("  ",))

    request = AppendNotesRequest(
        issue_id="at-123",
        notes=(" first note ", "second note", "first note"),
    )

    assert request.notes == ("first note", "second note")


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


def test_compatibility_routed_message_record_allows_missing_thread_identity() -> None:
    record = MessageRecord(
        id="msg-compat",
        title="Assigned planner note",
        delivery=MessageDelivery.COMPATIBILITY_ROUTED,
        audience=("planner",),
        queue="planner",
    )

    assert record.thread_id is None
    assert record.thread_kind is None


def test_store_message_contract_only_exposes_durable_threaded_path() -> None:
    assert tuple(item.value for item in MessageDelivery) == (
        "work-threaded",
        "compatibility-routed",
    )
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
    assert "compatibility-routed" in store_doc
    assert "implement `AtelierStore` itself" in store_doc
    assert "`atelier.lib.beads.Beads` remains the swappable boundary" in store_doc
    assert "Dual-Backend Proof" in store_doc
    assert "Downstream Migration Contract" in store_doc
    assert "Known Contract Gaps" in store_doc
    assert "dependency add/remove is not yet proven in the shared dual-backend suite" in store_doc
    assert "Planner, worker, and publish migrations should depend on `atelier.store`" in store_doc
    assert "Downstream epics can rely on the following store surface today" in store_doc
    assert "shared dual-backend parity for discovery/read flows" in store_doc
    assert "This proof slice leaves only the following work deferred" in store_doc
    assert "planner migrations onto `atelier.store`" in store_doc
    assert "publish/integration migrations onto `atelier.store`" in store_doc
    assert "The core store contract, discovery methods, mutation methods, and dual-backend" in (
        store_doc
    )
    assert "[Atelier Store Contract]" in beads_doc
    assert "[Atelier Store Contract]" in adoption_guide
    assert "Downstream migrations should import `atelier.store`" in adoption_guide
    assert "contract and concrete adapters for that layer now live in" in adoption_guide
    assert "process-backed coverage only" in adoption_guide


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


class _InMemorySubprocessTransport:
    """Drive ``SubprocessBeadsClient`` from the in-memory command backend."""

    def __init__(self, backend: InMemoryBeadsBackend) -> None:
        self._backend = backend

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        if request.argv in {
            ("bd", "dep", "add", "--help"),
            ("bd", "dep", "remove", "--help"),
        }:
            return BeadsCommandResult(argv=request.argv, returncode=0, stdout=_HELP)
        completed = self._backend.run(request.argv, cwd=request.cwd, env=request.env)
        return BeadsCommandResult(
            argv=request.argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _parity_seed_issues() -> tuple[dict[str, object], ...]:
    return (
        BUILDER.issue("at-epic", title="Epic", issue_type="epic", labels=("at:epic", "atelier")),
        BUILDER.issue(
            "at-change",
            title="Change",
            parent="at-epic",
            dependencies=("at-dep",),
            description=(
                "changeset.root_branch: root/store\n"
                "changeset.parent_branch: main\n"
                "changeset.work_branch: root/store-at-change\n"
                "changeset.root_base: abc1234\n"
                "changeset.parent_base: def5678\n"
                "pr_url: https://example.invalid/pr/41\n"
                "pr_number: 41\n"
                "pr_state: draft-pr\n"
                "review_owner: reviewer-a\n"
            ),
            labels=("atelier",),
        ),
        BUILDER.issue(
            "at-dep",
            title="Dependency",
            parent="at-epic",
            status="closed",
            description="pr_state: merged\n",
            labels=("atelier",),
        ),
        BUILDER.issue(
            "at-blocked",
            title="Blocked",
            parent="at-epic",
            status="blocked",
            labels=("atelier",),
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


def _store_for_backend(backend: str) -> AtelierStore:
    issues = _parity_seed_issues()
    if backend == "in-memory":
        client, _ = build_in_memory_beads_client(issues=issues)
        return build_atelier_store(beads=client)
    if backend == "subprocess":
        command_backend = InMemoryBeadsBackend(seeded_issues=issues)
        client = SubprocessBeadsClient(transport=_InMemorySubprocessTransport(command_backend))
        return build_atelier_store(beads=client)
    raise AssertionError(f"unexpected backend: {backend}")


def _read_snapshot(backend: str) -> dict[str, object]:
    store = _store_for_backend(backend)
    epic = _RUN(store.get_epic("at-epic"))
    parity = _RUN(store.epic_discovery_parity())
    changeset = _RUN(store.get_changeset("at-change"))
    listed_changesets = _RUN(store.list_changesets())
    ready_changesets = _RUN(store.list_ready_changesets())
    message = _RUN(store.list_messages(MessageQuery(unread_only=True)))[0]
    hook = _RUN(store.get_agent_hook("atelier/worker/agent"))
    return {
        "epics": tuple(epic_record.id for epic_record in _RUN(store.list_epics())),
        "parity": parity.model_dump(mode="json"),
        "epic_changesets": tuple(work_ref.id for work_ref in epic.changesets),
        "changeset": {
            "id": changeset.id,
            "epic_id": changeset.epic_id,
            "lifecycle": changeset.lifecycle.value,
            "branches": changeset.branches.model_dump() if changeset.branches else None,
            "review": changeset.review.model_dump(mode="json"),
            "dependencies": tuple(
                (
                    dependency.depends_on_id,
                    dependency.satisfied,
                    dependency.requires_integrated_state,
                    dependency.status.value if dependency.status is not None else None,
                )
                for dependency in changeset.dependencies
            ),
        },
        "listed_changesets": tuple(record.id for record in listed_changesets),
        "ready_changesets": tuple(record.id for record in ready_changesets),
        "message": {
            "id": message.id,
            "thread_id": message.thread_id,
            "thread_kind": message.thread_kind.value,
            "queue": message.queue,
            "audience": message.audience,
            "claimed_by": message.claimed_by,
            "blocking_roles": message.blocking_roles,
        },
        "hook": hook.model_dump(mode="json") if hook else None,
    }


def _mutation_snapshot(backend: str) -> dict[str, object]:
    store = _store_for_backend(backend)
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
    appended = _RUN(
        store.append_notes(
            AppendNotesRequest(
                issue_id="at-change",
                notes=("worker_update: preserved lifecycle mutation parity",),
            )
        )
    )
    transition = _RUN(
        store.transition_lifecycle(
            LifecycleTransitionRequest(
                issue_id="at-change",
                target_status=LifecycleStatus.IN_PROGRESS,
                expected_current=LifecycleStatus.OPEN,
            )
        )
    )
    created_message = _RUN(
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
    )
    claimed = _RUN(
        store.claim_message(
            ClaimMessageRequest(
                message_id="msg-queue",
                claimed_by="atelier/planner/codex/p200",
            )
        )
    )
    hooked = _RUN(
        store.set_agent_hook(SetHookRequest(agent_id="atelier/worker/agent", epic_id="at-epic"))
    )
    cleared = _RUN(
        store.clear_agent_hook(
            ClearHookRequest(agent_id="atelier/worker/agent", expected_epic_id="at-epic")
        )
    )
    refreshed = _RUN(store._show_issue("at-change"))
    return {
        "review": review.review.model_dump(mode="json"),
        "transition": transition.model_dump(mode="json"),
        "created_message": {
            "thread_id": created_message.thread_id,
            "thread_kind": created_message.thread_kind.value,
            "queue": created_message.queue,
            "audience": created_message.audience,
            "blocking": created_message.blocking,
        },
        "claimed": {
            "claimed_by": claimed.claimed_by,
            "queue": claimed.queue,
            "status": claimed.status.value if claimed.status else None,
        },
        "hooked": hooked.model_dump(mode="json"),
        "cleared": cleared.model_dump(mode="json") if cleared else None,
        "appended_tail": tuple((refreshed.description or "").rstrip("\n").splitlines()[-1:]),
        "appended_issue_lifecycle": appended.lifecycle.value,
        "refreshed_assignee": refreshed.assignee,
    }


@pytest.mark.parametrize("backend", _BACKENDS)
def test_store_dual_backend_read_snapshot_matches_expected_contract(backend: str) -> None:
    assert _read_snapshot(backend) == {
        "epics": ("at-epic",),
        "parity": {
            "active_top_level_work_count": 1,
            "indexed_active_epic_count": 1,
            "missing_executable_identity": [],
            "missing_from_index": [],
        },
        "epic_changesets": ("at-change", "at-dep", "at-blocked"),
        "changeset": {
            "id": "at-change",
            "epic_id": "at-epic",
            "lifecycle": "open",
            "branches": {
                "root_branch": "root/store",
                "parent_branch": "main",
                "work_branch": "root/store-at-change",
                "root_base": "abc1234",
                "parent_base": "def5678",
            },
            "review": {
                "pr_url": "https://example.invalid/pr/41",
                "pr_number": 41,
                "pr_state": "draft-pr",
                "review_owner": "reviewer-a",
                "integrated_sha": None,
            },
            "dependencies": (("at-dep", True, True, "closed"),),
        },
        "listed_changesets": ("at-change", "at-blocked"),
        "ready_changesets": ("at-change",),
        "message": {
            "id": "msg-queue",
            "thread_id": "at-change",
            "thread_kind": "changeset",
            "queue": "planner",
            "audience": ("planner",),
            "claimed_by": None,
            "blocking_roles": (),
        },
        "hook": None,
    }


@pytest.mark.parametrize("backend", _BACKENDS)
def test_store_epic_discovery_parity_reports_missing_identity(backend: str) -> None:
    issues = (
        BUILDER.issue(
            "at-missing",
            title="Missing identity",
            issue_type="task",
            status="open",
            labels=("atelier",),
        ),
        BUILDER.issue(
            "at-epic",
            title="Indexed epic",
            issue_type="epic",
            status="open",
            labels=("at:epic", "atelier"),
        ),
    )
    if backend == "in-memory":
        client, _ = build_in_memory_beads_client(issues=issues)
        store = build_atelier_store(beads=client)
    else:
        command_backend = InMemoryBeadsBackend(seeded_issues=issues)
        client = SubprocessBeadsClient(transport=_InMemorySubprocessTransport(command_backend))
        store = build_atelier_store(beads=client)

    parity = _RUN(store.epic_discovery_parity())

    assert parity.active_top_level_work_count == 2
    assert parity.indexed_active_epic_count == 1
    assert parity.in_parity is False
    assert tuple(item.issue_id for item in parity.missing_executable_identity) == ("at-missing",)
    assert parity.missing_executable_identity[0].remediation_command == (
        "bd update at-missing --type epic --add-label at:epic"
    )
    assert parity.missing_from_index == ()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_store_dual_backend_mutation_snapshot_matches_expected_contract(backend: str) -> None:
    assert _mutation_snapshot(backend) == {
        "review": {
            "pr_url": "https://example.invalid/pr/41",
            "pr_number": 41,
            "pr_state": "in-review",
            "review_owner": "reviewer-b",
            "integrated_sha": "abc1234",
        },
        "transition": {
            "issue_id": "at-change",
            "issue_kind": "changeset",
            "from_status": "open",
            "to_status": "in_progress",
            "reason": None,
        },
        "created_message": {
            "thread_id": "at-change",
            "thread_kind": "changeset",
            "queue": "planner",
            "audience": ("planner",),
            "blocking": True,
        },
        "claimed": {
            "claimed_by": "atelier/planner/codex/p200",
            "queue": "planner",
            "status": "open",
        },
        "hooked": {
            "agent_id": "atelier/worker/agent",
            "epic_id": "at-epic",
        },
        "cleared": {
            "agent_id": "atelier/worker/agent",
            "epic_id": "at-epic",
        },
        "appended_tail": ("worker_update: preserved lifecycle mutation parity",),
        "appended_issue_lifecycle": "open",
        "refreshed_assignee": None,
    }


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
    appended = _RUN(
        store.append_notes(
            AppendNotesRequest(
                issue_id="at-change",
                notes=("worker_update: preserved lifecycle mutation parity",),
            )
        )
    )
    assert appended.id == "at-change"
    _RUN(
        store.append_notes(
            AppendNotesRequest(
                issue_id="at-change",
                notes=("worker_update: preserved lifecycle mutation parity",),
            )
        )
    )
    refreshed = _RUN(store._show_issue("at-change"))
    assert refreshed.description is not None
    assert refreshed.description.count("worker_update: preserved lifecycle mutation parity") == 1
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


def test_beads_store_append_notes_fails_for_non_work_items() -> None:
    store = _store_for(_queue_message())

    with pytest.raises(ValueError, match="notes append requires work items"):
        _RUN(
            store.append_notes(
                AppendNotesRequest(
                    issue_id="msg-queue",
                    notes=("worker_update: this should fail",),
                )
            )
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


def test_beads_store_lists_compatibility_routed_messages() -> None:
    store = _store_for(
        BUILDER.issue(
            "msg-assigned",
            title="Assigned planner note",
            issue_type="message",
            labels=("at:message", "at:unread"),
            assignee="atelier/planner/codex/p200",
            description="Direct assignee routing.",
        ),
        BUILDER.issue(
            "msg-queue",
            title="Queue planner work",
            issue_type="message",
            labels=("at:message", "at:unread"),
            assignee="atelier/planner/codex/p200",
            description=render_message({"queue": "planner"}, "Need a decision."),
        ),
    )

    messages = _RUN(store.list_messages(MessageQuery(unread_only=True)))

    assert [message.id for message in messages] == ["msg-assigned", "msg-queue"]
    assert messages[0].delivery is MessageDelivery.COMPATIBILITY_ROUTED
    assert messages[0].audience == ("planner",)
    assert messages[0].thread_id is None
    assert messages[1].queue == "planner"
    assert messages[1].claimed_by == "atelier/planner/codex/p200"
