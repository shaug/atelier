from pathlib import Path

from atelier.lib.beads import SyncBeadsClient
from atelier.store import build_atelier_store
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
