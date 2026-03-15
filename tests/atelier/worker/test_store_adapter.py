from pathlib import Path

from atelier.lib.beads import IssueRecord, SyncBeadsClient
from atelier.messages import render_message
from atelier.store import StartupMessageRecord, build_atelier_store
from atelier.testing.beads import IssueFixtureBuilder
from atelier.testing.beads.client import build_in_memory_beads_client
from atelier.worker import store_adapter as worker_store


def _patch_bundle(monkeypatch, *, issues: tuple[dict[str, object], ...]) -> None:
    async_client, _issue_store = build_in_memory_beads_client(issues=issues)
    store = build_atelier_store(beads=async_client)
    worker_store.clear_bundle_cache()
    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=store,
            sync_client=SyncBeadsClient(async_client),
        ),
    )


def _worker_message(
    builder: IssueFixtureBuilder, message_id: str, *, thread_id: str
) -> dict[str, object]:
    return builder.issue(
        message_id,
        issue_type="message",
        labels=("at:message", "at:unread"),
        description=render_message(
            {
                "from": "atelier/planner/codex/p200",
                "delivery": "work-threaded",
                "thread": thread_id,
                "thread_kind": "changeset" if "." in thread_id else "epic",
                "audience": ["worker"],
                "kind": "instruction",
                "blocking": True,
            },
            "Follow these instructions.",
        ),
    )


def test_claim_epic_marks_in_progress_and_hooked(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    agent_id = "atelier/worker/codex/p100"
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic",),
                status="open",
            ),
        ),
    )

    claimed = worker_store.claim_epic(
        "at-epic",
        agent_id,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert claimed["assignee"] == agent_id
    assert claimed["status"] == "in_progress"
    assert "at:hooked" in claimed["labels"]
    worker_store.clear_bundle_cache()


def test_release_epic_assignment_clears_assignee_and_hook_label(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    agent_id = "atelier/worker/codex/p100"
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic", "at:hooked"),
                status="in_progress",
                assignee=agent_id,
            ),
        ),
    )

    released = worker_store.release_epic_assignment(
        "at-epic",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        expected_assignee=agent_id,
        expected_hooked=True,
    )
    refreshed = worker_store.show_issue(
        "at-epic",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert released is True
    assert refreshed is not None
    assert refreshed["status"] == "open"
    assert not refreshed.get("assignee")
    assert "at:hooked" not in refreshed["labels"]
    worker_store.clear_bundle_cache()


def test_list_work_children_filters_non_work_children(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic",),
                children=("at-epic.1", "at-msg"),
            ),
            builder.issue(
                "at-epic.1",
                issue_type="task",
                parent="at-epic",
                status="open",
            ),
            builder.issue(
                "at-msg",
                issue_type="message",
                parent="at-epic",
                status="open",
            ),
        ),
    )

    children = worker_store.list_work_children(
        "at-epic",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        include_closed=True,
    )

    assert [child["id"] for child in children] == ["at-epic.1"]
    worker_store.clear_bundle_cache()


def test_list_epics_uses_label_scoped_typed_scan(monkeypatch) -> None:
    seen: list[tuple[tuple[str, ...], int | None, bool]] = []

    class _FakeSyncClient:
        def list(self, request):
            seen.append((request.labels, request.limit, request.include_closed))
            label = request.labels[0]
            if label == "at:epic":
                return (IssueRecord(id="at-epic", title="Primary", status="open"),)
            return (IssueRecord(id="at-epic", title="Primary duplicate", status="open"),)

    monkeypatch.setattr(
        worker_store.beads,
        "issue_label_candidates",
        lambda *_args, **_kwargs: ("at:epic", "ts:epic"),
    )
    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=build_atelier_store(beads=build_in_memory_beads_client()[0]),
            sync_client=_FakeSyncClient(),
        ),
    )
    worker_store.clear_bundle_cache()

    epics = worker_store.list_epics(
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        include_closed=True,
    )

    assert [epic["id"] for epic in epics] == ["at-epic"]
    assert seen == [
        (("at:epic",), 10_000, True),
        (("ts:epic",), 10_000, True),
    ]
    worker_store.clear_bundle_cache()


def test_list_inbox_messages_uses_typed_startup_store_method(monkeypatch) -> None:
    class _FakeStore:
        async def list_startup_messages(self, _query):
            return (
                StartupMessageRecord(
                    id="at-msg",
                    title="Worker instruction",
                    body="Follow these instructions.",
                    thread_id="at-epic.1",
                    thread_kind="changeset",
                    audience=("worker",),
                    kind="instruction",
                    blocking_roles=("worker",),
                ),
            )

        async def list_messages(self, _query):
            raise AssertionError("list_messages fallback should not be used")

    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=_FakeStore(),
            sync_client=SyncBeadsClient(build_in_memory_beads_client()[0]),
        ),
    )
    monkeypatch.setattr(
        worker_store,
        "_show_issue",
        lambda **_kwargs: {
            "id": "at-epic.1",
            "status": "open",
            "labels": ["at:changeset"],
        },
    )
    worker_store.clear_bundle_cache()

    inbox = worker_store.list_inbox_messages(
        "atelier/worker/codex/p100",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert [item["id"] for item in inbox] == ["at-msg"]
    worker_store.clear_bundle_cache()


def test_find_agent_bead_scans_beyond_default_list_cap(monkeypatch) -> None:
    seen_limits: list[int | None] = []
    candidate_issues = tuple(
        IssueRecord(
            id=f"at-agent-{index:02d}",
            title=f"atelier/worker/codex/p100-extra-{index:02d}",
        )
        for index in range(55)
    ) + (
        IssueRecord(
            id="at-agent-match",
            title="atelier/worker/codex/p100",
            status="open",
        ),
    )

    class _FakeSyncClient:
        def list(self, request):
            seen_limits.append(request.limit)
            title_query = request.title_query or ""
            matching = tuple(
                issue for issue in candidate_issues if title_query in (issue.title or "")
            )
            effective_limit = 50 if request.limit is None else request.limit
            return matching[:effective_limit]

    monkeypatch.setattr(
        worker_store.beads,
        "_agent_label_candidates",
        lambda **_kwargs: ("at:agent",),
    )
    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=build_atelier_store(beads=build_in_memory_beads_client()[0]),
            sync_client=_FakeSyncClient(),
        ),
    )
    worker_store.clear_bundle_cache()

    bead = worker_store.find_agent_bead(
        "atelier/worker/codex/p100",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert bead is not None
    assert bead["id"] == "at-agent-match"
    assert bead["title"] == "atelier/worker/codex/p100"
    assert bead["status"] == "open"
    assert seen_limits == [10_000]
    worker_store.clear_bundle_cache()


def test_find_agent_bead_fails_closed_when_agent_scan_hits_limit(monkeypatch) -> None:
    class _FakeSyncClient:
        def list(self, request):
            return tuple(
                IssueRecord(
                    id=f"at-agent-{index:05d}",
                    title=f"atelier/worker/codex/p100-{index:05d}",
                )
                for index in range(request.limit or 0)
            )

    monkeypatch.setattr(
        worker_store.beads,
        "_agent_label_candidates",
        lambda **_kwargs: ("at:agent",),
    )
    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=build_atelier_store(beads=build_in_memory_beads_client()[0]),
            sync_client=_FakeSyncClient(),
        ),
    )
    worker_store.clear_bundle_cache()

    try:
        try:
            worker_store.find_agent_bead(
                "atelier/worker/codex/p100",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )
        except RuntimeError as exc:
            assert "agent label scan reached the configured limit" in str(exc)
        else:
            raise AssertionError("expected agent label scan overflow to fail closed")
    finally:
        worker_store.clear_bundle_cache()


def test_list_inbox_messages_skips_closed_changeset_threads(monkeypatch) -> None:
    worker_store.clear_bundle_cache()
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue("at-epic", issue_type="epic", labels=("at:epic",), status="open"),
            builder.issue(
                "at-epic.1",
                issue_type="task",
                parent="at-epic",
                status="closed",
                labels=("cs:merged",),
            ),
            _worker_message(builder, "at-msg", thread_id="at-epic.1"),
        ),
    )

    inbox = worker_store.list_inbox_messages(
        "atelier/worker/codex/p100",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert inbox == []
    worker_store.clear_bundle_cache()


def test_list_inbox_messages_keeps_open_changeset_threads(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue("at-epic", issue_type="epic", labels=("at:epic",), status="open"),
            builder.issue(
                "at-epic.1",
                issue_type="task",
                parent="at-epic",
                status="open",
            ),
            _worker_message(builder, "at-msg", thread_id="at-epic.1"),
        ),
    )

    inbox = worker_store.list_inbox_messages(
        "atelier/worker/codex/p100",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert len(inbox) == 1
    assert inbox[0]["id"] == "at-msg"
    worker_store.clear_bundle_cache()


def test_list_inbox_messages_skips_closed_epic_threads(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue("at-epic", issue_type="epic", labels=("at:epic",), status="closed"),
            _worker_message(builder, "at-msg", thread_id="at-epic"),
        ),
    )

    inbox = worker_store.list_inbox_messages(
        "atelier/worker/codex/p100",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert inbox == []
    worker_store.clear_bundle_cache()
