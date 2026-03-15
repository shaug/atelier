from __future__ import annotations

from pathlib import Path

from atelier import planner_overview
from atelier.store import build_atelier_store
from atelier.testing.beads import build_in_memory_beads_client


def test_list_epics_accepts_store_shaped_dependency_payloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    client, _store = build_in_memory_beads_client(
        issues=(
            {
                "id": "at-dep",
                "title": "Dependency",
                "issue_type": "task",
                "status": "in_progress",
                "labels": [],
            },
            {
                "id": "at-epic",
                "title": "Epic with dependency",
                "issue_type": "epic",
                "status": "open",
                "labels": ["at:epic"],
                "dependencies": [
                    {
                        "issue_id": "at-epic",
                        "depends_on_id": "at-dep",
                        "type": "blocks",
                    }
                ],
            },
        )
    )
    monkeypatch.setattr(
        planner_overview,
        "_build_store",
        lambda **_kwargs: build_atelier_store(beads=client),
    )

    issues = planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)

    assert len(issues) == 1
    assert issues[0]["id"] == "at-epic"
    assert issues[0]["dependencies"] == [{"id": "at-dep", "status": "in_progress"}]
    assert "Blocked epics:" in planner_overview.render_epics(issues, show_drafts=True)
