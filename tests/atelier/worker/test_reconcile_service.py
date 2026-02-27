from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atelier.worker import reconcile_service, selection


def test_resolve_epic_id_for_changeset_uses_parent_when_parent_id_is_null(monkeypatch) -> None:
    changeset = {
        "id": "at-yuzo.5",
        "status": "in_progress",
        "labels": ["at:changeset"],
        "parent_id": None,
        "parent": "at-yuzo",
    }
    epic = {
        "id": "at-yuzo",
        "status": "open",
        "labels": ["at:epic"],
    }

    def run_bd_issue_records(args: list[str], **_kwargs: object) -> list[SimpleNamespace]:
        if args == ["show", "at-yuzo.5"]:
            return [SimpleNamespace(raw=changeset)]
        if args == ["show", "at-yuzo"]:
            return [SimpleNamespace(raw=epic)]
        return []

    monkeypatch.setattr(reconcile_service.beads, "run_bd_issue_records", run_bd_issue_records)

    resolved = reconcile_service.resolve_epic_id_for_changeset(
        changeset,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        issue_labels=selection.issue_labels,
        issue_parent_id=selection.issue_parent_id,
    )

    assert resolved == "at-yuzo"
