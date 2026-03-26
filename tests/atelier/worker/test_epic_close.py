from pathlib import Path

from atelier.store import LifecycleStatus, ReviewMetadata, ReviewState
from atelier.worker import epic_close
from atelier.worker import store_adapter as worker_store


def test_close_epic_if_complete_uses_typed_store_summary(monkeypatch) -> None:
    summary = worker_store.EpicChangesetSummary(
        total=2,
        ready=1,
        merged=1,
        abandoned=1,
        remaining=0,
    )
    candidate = worker_store.EpicCloseCandidate(
        id="at-epic.1",
        lifecycle=LifecycleStatus.CLOSED,
        review=ReviewMetadata(pr_state=ReviewState.MERGED),
    )
    confirmations: list[worker_store.EpicChangesetSummary] = []
    transitions: list[str] = []
    cleared_hooks: list[str] = []

    monkeypatch.setattr(
        worker_store,
        "show_issue_lifecycle",
        lambda issue_id, *, beads_root, repo_root: LifecycleStatus.IN_PROGRESS,
    )
    monkeypatch.setattr(
        worker_store,
        "has_work_children",
        lambda epic_id, *, beads_root, repo_root, include_closed: True,
    )
    monkeypatch.setattr(
        worker_store,
        "list_epic_close_candidates",
        lambda epic_id, *, beads_root, repo_root, include_closed: [candidate],
    )
    monkeypatch.setattr(
        worker_store,
        "epic_changeset_summary",
        lambda epic_id, *, beads_root, repo_root: summary,
    )
    monkeypatch.setattr(
        worker_store,
        "transition_lifecycle",
        lambda issue_id, *, target_status, beads_root, repo_root: transitions.append(issue_id),
    )
    monkeypatch.setattr(
        worker_store,
        "clear_agent_hook",
        lambda agent_bead_id, *, beads_root, repo_root, expected_hook: cleared_hooks.append(
            agent_bead_id
        ),
    )

    closed = epic_close.close_epic_if_complete(
        "at-epic",
        "at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        confirm=lambda received: confirmations.append(received) or True,
    )

    assert closed is True
    assert confirmations == [summary]
    assert transitions == ["at-epic"]
    assert cleared_hooks == ["at-agent"]


def test_close_epic_if_complete_reopens_active_pr_candidate(monkeypatch) -> None:
    candidate = worker_store.EpicCloseCandidate(
        id="at-epic.1",
        lifecycle=LifecycleStatus.CLOSED,
        review=ReviewMetadata(pr_state=ReviewState.PR_OPEN),
    )
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(
        worker_store,
        "show_issue_lifecycle",
        lambda issue_id, *, beads_root, repo_root: LifecycleStatus.IN_PROGRESS,
    )
    monkeypatch.setattr(
        worker_store,
        "has_work_children",
        lambda epic_id, *, beads_root, repo_root, include_closed: True,
    )
    monkeypatch.setattr(
        worker_store,
        "list_epic_close_candidates",
        lambda epic_id, *, beads_root, repo_root, include_closed: [candidate],
    )
    monkeypatch.setattr(
        worker_store,
        "transition_lifecycle",
        lambda issue_id, *, target_status, beads_root, repo_root: events.append(
            ("transition", issue_id)
        ),
    )
    monkeypatch.setattr(
        worker_store,
        "reconcile_reopened_external_tickets",
        lambda issue_id, *, beads_root, repo_root: events.append(("reconcile", issue_id)),
    )

    closed = epic_close.close_epic_if_complete(
        "at-epic",
        "at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert closed is False
    assert events == [("transition", "at-epic.1"), ("reconcile", "at-epic.1")]
