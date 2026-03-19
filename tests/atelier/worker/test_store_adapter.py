import datetime as dt
from pathlib import Path
from unittest.mock import patch

from atelier.lib.beads import IssueRecord, SyncBeadsClient
from atelier.messages import render_message
from atelier.store import HookRecord, StartupMessageRecord, build_atelier_store
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


def test_update_changeset_review_updates_pr_state_via_store(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic",),
                children=("at-epic.1",),
            ),
            builder.issue(
                "at-epic.1",
                issue_type="task",
                parent="at-epic",
                status="blocked",
                description="pr_state: pushed\n",
            ),
        ),
    )

    worker_store.update_changeset_review(
        "at-epic.1",
        pr_state="merged",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    updated = worker_store.show_issue(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert updated is not None
    assert "pr_state: merged" in str(updated.get("description"))
    worker_store.clear_bundle_cache()


def test_update_changeset_integrated_sha_preserves_existing_review_fields(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic",
                issue_type="epic",
                labels=("at:epic",),
                children=("at-epic.1",),
            ),
            builder.issue(
                "at-epic.1",
                issue_type="task",
                parent="at-epic",
                status="blocked",
                description="pr_state: merged\n",
            ),
        ),
    )

    worker_store.update_changeset_integrated_sha(
        "at-epic.1",
        "abc1234",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    updated = worker_store.show_issue(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert updated is not None
    description = str(updated.get("description"))
    assert "pr_state: merged" in description
    assert "changeset.integrated_sha: abc1234" in description
    worker_store.clear_bundle_cache()


def test_transition_lifecycle_updates_changeset_status(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(builder.issue("at-epic.1", issue_type="task", status="open"),),
    )

    worker_store.transition_lifecycle(
        "at-epic.1",
        target_status="blocked",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    refreshed = worker_store.show_issue(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert refreshed is not None
    assert refreshed["status"] == "blocked"
    worker_store.clear_bundle_cache()


def test_mark_issue_blocked_updates_status_and_note_together(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(builder.issue("at-epic.1", issue_type="task", status="open"),),
    )

    worker_store.mark_issue_blocked(
        "at-epic.1",
        reason="missing integration",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    refreshed = worker_store.show_issue(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert refreshed is not None
    assert refreshed["status"] == "blocked"
    assert "blocked_at:" in str(refreshed.get("description"))
    assert "missing integration" in str(refreshed.get("description"))
    worker_store.clear_bundle_cache()


def test_mark_issue_blocked_fails_closed_when_combined_update_cannot_be_verified(
    monkeypatch,
) -> None:
    requests = []

    class _FakeSyncClient:
        def update(self, request):
            requests.append(request)
            return IssueRecord(id=request.issue_id, title="Stale", status="open")

    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=build_atelier_store(beads=build_in_memory_beads_client()[0]),
            sync_client=_FakeSyncClient(),
        ),
    )
    monkeypatch.setattr(
        worker_store,
        "_show_issue",
        lambda **_kwargs: {
            "id": "at-epic.1",
            "status": "open",
            "description": "",
        },
    )
    worker_store.clear_bundle_cache()

    try:
        try:
            worker_store.mark_issue_blocked(
                "at-epic.1",
                reason="missing integration",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )
        except RuntimeError as exc:
            assert "blocked transition could not be verified" in str(exc)
        else:
            raise AssertionError("expected blocked transition verification to fail closed")
    finally:
        worker_store.clear_bundle_cache()

    assert len(requests) == 5
    descriptions = {request.description for request in requests}
    assert len(descriptions) == 1
    for request in requests:
        assert request.status == "blocked"
        assert request.description is not None
        assert "blocked_at:" in request.description
        assert "missing integration" in request.description
        assert request.description.count("blocked_at:") == 1


def test_mark_issue_blocked_reuses_same_note_when_retry_reads_partial_state(
    monkeypatch,
) -> None:
    requests = []
    real_datetime = dt.datetime
    descriptions = iter(
        (
            {"id": "at-epic.1", "status": "open", "description": ""},
            None,
            {
                "id": "at-epic.1",
                "status": "open",
                "description": "blocked_at: 2026-03-15T18:28:04+00:00 reason: missing integration\n",
            },
            {
                "id": "at-epic.1",
                "status": "blocked",
                "description": "blocked_at: 2026-03-15T18:28:04+00:00 reason: missing integration\n",
            },
        )
    )

    class _FakeSyncClient:
        def update(self, request):
            requests.append(request)
            return IssueRecord(id=request.issue_id, title="Stale", status="open")

    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=build_atelier_store(beads=build_in_memory_beads_client()[0]),
            sync_client=_FakeSyncClient(),
        ),
    )
    monkeypatch.setattr(
        worker_store,
        "_show_issue",
        lambda **_kwargs: next(descriptions),
    )
    monkeypatch.setattr(
        worker_store.dt,
        "datetime",
        type(
            "_FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: real_datetime.fromisoformat("2026-03-15T18:28:04+00:00")
                )
            },
        ),
    )
    worker_store.clear_bundle_cache()

    try:
        worker_store.mark_issue_blocked(
            "at-epic.1",
            reason="missing integration",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
    finally:
        worker_store.clear_bundle_cache()

    assert len(requests) == 2
    assert requests[0].description == requests[1].description
    assert requests[1].description is not None
    assert requests[1].description.count("blocked_at:") == 1


def test_update_changeset_review_preserves_existing_review_fields(monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    _patch_bundle(
        monkeypatch,
        issues=(
            builder.issue(
                "at-epic.1",
                issue_type="task",
                status="open",
                description=(
                    "pr_url: https://example.test/pr/1\n"
                    "pr_number: 1\n"
                    "pr_state: draft-pr\n"
                    "review_owner: reviewer-a\n"
                ),
            ),
        ),
    )

    worker_store.update_changeset_review(
        "at-epic.1",
        pr_state="in-review",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        preserve_existing=True,
    )

    refreshed = worker_store.show_issue(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert refreshed is not None
    assert "pr_url: https://example.test/pr/1" in str(refreshed["description"])
    assert "pr_number: 1" in str(refreshed["description"])
    assert "pr_state: in-review" in str(refreshed["description"])
    assert "review_owner: reviewer-a" in str(refreshed["description"])
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


def test_get_agent_hook_uses_agent_bead_store_method(monkeypatch) -> None:
    class _FakeStore:
        async def get_agent_bead_hook(self, agent_bead_id):
            assert agent_bead_id == "at-agent"
            return HookRecord(agent_id="atelier/worker/codex/p100", epic_id="at-epic")

        async def get_agent_hook(self, _agent_id):
            raise AssertionError("agent-id hook lookup should not be used")

    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=_FakeStore(),
            sync_client=SyncBeadsClient(build_in_memory_beads_client()[0]),
        ),
    )
    worker_store.clear_bundle_cache()

    hook = worker_store.get_agent_hook(
        "at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert hook == "at-epic"
    worker_store.clear_bundle_cache()


def test_agent_hook_mutations_use_agent_bead_store_methods(monkeypatch) -> None:
    seen: list[tuple[str, str, str | None]] = []

    class _FakeStore:
        async def set_agent_bead_hook(self, request):
            seen.append(("set", request.agent_bead_id, request.epic_id))
            return HookRecord(agent_id="atelier/worker/codex/p100", epic_id=request.epic_id)

        async def clear_agent_bead_hook(self, request):
            seen.append(("clear", request.agent_bead_id, request.expected_epic_id))
            return HookRecord(
                agent_id="atelier/worker/codex/p100",
                epic_id=request.expected_epic_id or "at-epic",
            )

        async def set_agent_hook(self, _request):
            raise AssertionError("agent-id hook mutation should not be used")

        async def clear_agent_hook(self, _request):
            raise AssertionError("agent-id hook mutation should not be used")

    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=_FakeStore(),
            sync_client=SyncBeadsClient(build_in_memory_beads_client()[0]),
        ),
    )
    worker_store.clear_bundle_cache()

    worker_store.set_agent_hook(
        "at-agent",
        "at-epic",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    worker_store.clear_agent_hook(
        "at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        expected_hook="at-epic",
    )

    assert seen == [
        ("set", "at-agent", "at-epic"),
        ("clear", "at-agent", "at-epic"),
    ]
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


def test_list_inbox_messages_skips_merged_changeset_threads(monkeypatch) -> None:
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
                description="pr_state: merged\nchangeset.integrated_sha: abc1234\n",
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


def test_list_inbox_messages_keeps_open_changeset_threads_with_closed_pr_state(
    monkeypatch,
) -> None:
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
                description="pr_state: closed\n",
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
