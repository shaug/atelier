from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from atelier.lib.beads import SyncBeadsClient
from atelier.store import build_atelier_store
from atelier.testing.beads import InMemoryBeadsBackend, IssueFixtureBuilder, patch_in_memory_beads
from atelier.testing.beads.client import InMemoryBeadsClient
from atelier.worker import changeset_state


def _seed_backend(
    tmp_path: Path, *issues: dict[str, object]
) -> tuple[InMemoryBeadsBackend, Path, Path]:
    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    return InMemoryBeadsBackend(seeded_issues=issues), beads_root, repo_root


@contextmanager
def _patched_backend(monkeypatch, backend: InMemoryBeadsBackend):
    async_client = InMemoryBeadsClient(issue_store=backend.state)
    store = build_atelier_store(beads=async_client)
    changeset_state.worker_store.clear_bundle_cache()
    monkeypatch.setattr(
        changeset_state.worker_store,
        "_build_store_bundle",
        lambda **_kwargs: changeset_state.worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=store,
            sync_client=SyncBeadsClient(async_client),
        ),
    )
    with patch_in_memory_beads(backend):
        yield
    changeset_state.worker_store.clear_bundle_cache()


def test_mark_changeset_blocked_adds_blocked_state_and_note(tmp_path: Path, monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Blocked changeset", status="open"),
    )

    with _patched_backend(monkeypatch, backend):
        changeset_state.mark_changeset_blocked(
            "at-1",
            beads_root=beads_root,
            repo_root=repo_root,
            reason="missing integration",
        )

    issue = backend.state.show("at-1")
    assert issue["status"] == "blocked"
    assert "blocked_at:" in str(issue.get("description"))
    assert "missing integration" in str(issue.get("description"))


def test_close_completed_container_changesets_closes_eligible_nodes(
    tmp_path: Path, monkeypatch
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Epic", issue_type="epic", labels=("at:epic",)),
        builder.issue(
            "at-1.1",
            title="Merged descendant",
            parent="at-1",
            status="done",
            labels=("cs:merged",),
        ),
        builder.issue(
            "at-1.2",
            title="Abandoned descendant",
            parent="at-1",
            status="done",
            labels=("cs:abandoned",),
        ),
        builder.issue("at-1.3", title="Open descendant", parent="at-1", status="open"),
        builder.issue(
            "at-1.4",
            title="Unknown status descendant",
            parent="at-1",
            status="custom",
        ),
    )

    with _patched_backend(monkeypatch, backend):
        closed = changeset_state.close_completed_container_changesets(
            "at-1",
            beads_root=beads_root,
            repo_root=repo_root,
            has_open_descendant_changesets=lambda issue_id: issue_id == "at-1.2",
        )

    assert closed == ["at-1.1"]
    assert backend.state.show("at-1.1")["status"] == "closed"
    assert backend.state.show("at-1.2")["status"] == "done"
    assert backend.state.show("at-1.3")["status"] == "open"


def test_close_completed_container_changesets_reopens_active_pr_changeset(
    tmp_path: Path, monkeypatch
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Epic", issue_type="epic", labels=("at:epic",)),
        builder.issue(
            "at-1.1",
            title="Active PR descendant",
            parent="at-1",
            status="done",
            labels=("cs:merged",),
            description="pr_state: pr-open\n",
        ),
    )

    with _patched_backend(monkeypatch, backend):
        closed = changeset_state.close_completed_container_changesets(
            "at-1",
            beads_root=beads_root,
            repo_root=repo_root,
            has_open_descendant_changesets=lambda _issue_id: False,
        )

    assert closed == []
    assert backend.state.show("at-1.1")["status"] == "in_progress"


def test_close_completed_ancestor_container_changesets_closes_claimed_lineage_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Epic", issue_type="epic", labels=("at:epic",)),
        builder.issue("at-1.1", title="Parent", parent="at-1", status="in_progress"),
        builder.issue("at-1.2", title="Grandparent", parent="at-1.1", status="in_progress"),
        builder.issue("at-1.2.1", title="Leaf", parent="at-1.2", status="closed"),
    )

    with _patched_backend(monkeypatch, backend):
        closed = changeset_state.close_completed_ancestor_container_changesets(
            "at-1.2.1",
            beads_root=beads_root,
            repo_root=repo_root,
            has_open_descendant_changesets=lambda _issue_id: False,
        )

    assert closed == ["at-1.2", "at-1.1"]
    assert backend.state.show("at-1.2")["status"] == "closed"
    assert backend.state.show("at-1.1")["status"] == "closed"


def test_close_completed_ancestor_container_changesets_stops_when_ancestor_has_open_descendants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Epic", issue_type="epic", labels=("at:epic",)),
        builder.issue("at-1.1", title="Parent", parent="at-1", status="in_progress"),
        builder.issue("at-1.2", title="Grandparent", parent="at-1.1", status="in_progress"),
        builder.issue("at-1.2.1", title="Leaf", parent="at-1.2", status="closed"),
    )

    with _patched_backend(monkeypatch, backend):
        closed = changeset_state.close_completed_ancestor_container_changesets(
            "at-1.2.1",
            beads_root=beads_root,
            repo_root=repo_root,
            has_open_descendant_changesets=lambda issue_id: issue_id == "at-1.1",
        )

    assert closed == ["at-1.2"]
    assert backend.state.show("at-1.2")["status"] == "closed"
    assert backend.state.show("at-1.1")["status"] == "in_progress"


def test_promote_planned_descendant_changesets_promotes_deferred_only(
    tmp_path: Path, monkeypatch
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue("at-1", title="Epic", issue_type="epic", labels=("at:epic",)),
        builder.issue("at-1.1", title="Deferred child", parent="at-1", status="deferred"),
        builder.issue("at-1.2", title="Open child", parent="at-1", status="open"),
    )

    with _patched_backend(monkeypatch, backend):
        promoted = changeset_state.promote_planned_descendant_changesets(
            "at-1", beads_root=beads_root, repo_root=repo_root
        )

    assert promoted == ["at-1.1"]
    assert backend.state.show("at-1.1")["status"] == "open"
    assert backend.state.show("at-1.2")["status"] == "open"


def test_mark_changeset_in_progress_reconciles_reopened_external_tickets() -> None:
    with (
        patch(
            "atelier.worker.changeset_state.worker_store.transition_lifecycle"
        ) as transition_lifecycle,
        patch(
            "atelier.worker.changeset_state.worker_store.reconcile_reopened_external_tickets"
        ) as reconcile_reopened,
    ):
        changeset_state.mark_changeset_in_progress(
            "at-1.5",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    transition_lifecycle.assert_called_once_with(
        "at-1.5",
        target_status="in_progress",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    reconcile_reopened.assert_called_once_with(
        "at-1.5",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )


def test_mark_changeset_merged_reconciles_external_tickets(tmp_path: Path, monkeypatch) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue(
            "at-1.1",
            title="Merged changeset",
            status="open",
            description="pr_state: merged\n",
            labels=("cs:abandoned",),
        ),
    )

    with _patched_backend(monkeypatch, backend):
        changeset_state.mark_changeset_merged(
            "at-1.1",
            beads_root=beads_root,
            repo_root=repo_root,
        )

    issue = backend.state.show("at-1.1")
    assert issue["status"] == "closed"
    assert "cs:merged" in issue["labels"]
    assert "cs:abandoned" not in issue["labels"]


def test_mark_changeset_abandoned_sets_terminal_marker_and_reconciles_external_tickets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue(
            "at-1.2",
            title="Abandoned changeset",
            status="open",
            description="pr_state: closed\n",
            labels=("cs:merged",),
        ),
    )

    with _patched_backend(monkeypatch, backend):
        changeset_state.mark_changeset_abandoned(
            "at-1.2",
            beads_root=beads_root,
            repo_root=repo_root,
        )

    issue = backend.state.show("at-1.2")
    assert issue["status"] == "closed"
    assert "cs:abandoned" in issue["labels"]
    assert "cs:merged" not in issue["labels"]


def test_mark_changeset_merged_reopens_when_pr_lifecycle_is_active(
    tmp_path: Path, monkeypatch
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue(
            "at-1.3",
            title="Active review changeset",
            status="open",
            description="pr_state: in-review\n",
        ),
    )

    with _patched_backend(monkeypatch, backend):
        with patch.object(
            changeset_state.beads,
            "close_transition_has_active_pr_lifecycle",
            side_effect=AssertionError("worker close guard should not use the legacy seam"),
        ):
            changeset_state.mark_changeset_merged(
                "at-1.3",
                beads_root=beads_root,
                repo_root=repo_root,
            )

    issue = backend.state.show("at-1.3")
    assert issue["status"] == "in_progress"
    assert "cs:merged" not in issue["labels"]


def test_mark_changeset_abandoned_reopens_when_pr_lifecycle_is_active(
    tmp_path: Path, monkeypatch
) -> None:
    builder = IssueFixtureBuilder()
    backend, beads_root, repo_root = _seed_backend(
        tmp_path,
        builder.issue(
            "at-1.4",
            title="Draft PR changeset",
            status="open",
            description="pr_state: draft-pr\n",
        ),
    )

    with _patched_backend(monkeypatch, backend):
        with patch.object(
            changeset_state.beads,
            "close_transition_has_active_pr_lifecycle",
            side_effect=AssertionError("worker close guard should not use the legacy seam"),
        ):
            changeset_state.mark_changeset_abandoned(
                "at-1.4",
                beads_root=beads_root,
                repo_root=repo_root,
            )

    issue = backend.state.show("at-1.4")
    assert issue["status"] == "in_progress"
    assert "cs:abandoned" not in issue["labels"]
