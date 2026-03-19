from pathlib import Path
from unittest.mock import patch

from atelier.worker import external_ticket_reopen_compat


def test_reconcile_reopened_exported_github_tickets_delegates_to_beads() -> None:
    with patch(
        "atelier.worker.external_ticket_reopen_compat.beads."
        "reconcile_reopened_issue_exported_github_tickets",
        return_value="reopened",
    ) as reconcile:
        result = external_ticket_reopen_compat.reconcile_reopened_exported_github_tickets(
            "at-1.2",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result == "reopened"
    reconcile.assert_called_once_with(
        "at-1.2",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
