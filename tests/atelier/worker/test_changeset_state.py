from pathlib import Path
from unittest.mock import patch

from atelier.worker import changeset_state


def test_mark_changeset_blocked_adds_blocked_state_and_note() -> None:
    with patch("atelier.worker.changeset_state.beads.run_bd_command") as run_bd_command:
        changeset_state.mark_changeset_blocked(
            "at-1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            reason="missing integration",
        )

    args = run_bd_command.call_args.args[0]
    assert args[0:2] == ["update", "at-1"]
    assert "--status" in args
    assert "blocked" in args
    assert "--append-notes" in args
    assert "missing integration" in args[-1]


def test_close_completed_container_changesets_closes_eligible_nodes() -> None:
    descendants = [
        {
            "id": "at-1.1",
            "status": "done",
            "labels": ["cs:merged"],
        },
        {
            "id": "at-1.2",
            "status": "done",
            "labels": ["cs:abandoned"],
        },
        {
            "id": "at-1.3",
            "status": "open",
            "labels": ["cs:ready"],
        },
        {
            "id": "at-1.4",
            "status": "",
            "labels": ["cs:merged"],
        },
    ]
    with (
        patch(
            "atelier.worker.changeset_state.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch("atelier.worker.changeset_state.mark_changeset_closed") as mark_closed,
    ):
        closed = changeset_state.close_completed_container_changesets(
            "at-1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            has_open_descendant_changesets=lambda issue_id: issue_id == "at-1.2",
        )

    assert closed == ["at-1.1"]
    mark_closed.assert_called_once_with(
        "at-1.1", beads_root=Path("/beads"), repo_root=Path("/repo")
    )


def test_promote_planned_descendant_changesets_promotes_deferred_only() -> None:
    descendants = [
        {"id": "at-1.1", "status": "deferred", "labels": ["cs:planned"]},
        {"id": "at-1.2", "status": "open", "labels": ["cs:ready"]},
    ]
    with (
        patch(
            "atelier.worker.changeset_state.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch("atelier.worker.changeset_state.beads.run_bd_command") as run_bd_command,
    ):
        promoted = changeset_state.promote_planned_descendant_changesets(
            "at-1", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert promoted == ["at-1.1"]
    run_bd_command.assert_called_once()


def test_mark_changeset_merged_reconciles_external_tickets() -> None:
    with (
        patch("atelier.worker.changeset_state.beads.run_bd_command"),
        patch(
            "atelier.worker.changeset_state.beads.reconcile_closed_issue_exported_github_tickets"
        ) as reconcile,
    ):
        changeset_state.mark_changeset_merged(
            "at-1.1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    reconcile.assert_called_once_with(
        "at-1.1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
