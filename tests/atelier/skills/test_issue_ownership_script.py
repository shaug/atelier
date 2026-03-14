from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from atelier.store import build_atelier_store
from atelier.testing.beads import IssueFixtureBuilder, build_in_memory_beads_client

BUILDER = IssueFixtureBuilder()


def _load_script():
    scripts_dir = Path(__file__).resolve().parents[3] / "src/atelier/skills/beads/scripts"
    path = scripts_dir / "check_issue_ownership.py"
    spec = importlib.util.spec_from_file_location("test_check_issue_ownership_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_issue_ownership_uses_assignee_not_owner() -> None:
    module = _load_script()
    issue = {
        "id": "at-1",
        "title": "Assigned to worker",
        "status": "in_progress",
        "labels": ["at:epic"],
        "owner": "planner@example.com",
        "assignee": "atelier/worker/codex/p100",
    }

    summary = module.planner_issue_ownership.summarize_issue_ownership(issue)
    rendered = module.planner_issue_ownership.render_issue_ownership(summary)

    assert summary.owner_metadata == "planner@example.com"
    assert summary.assignee == "atelier/worker/codex/p100"
    assert summary.assignee_role == "worker"
    assert "- execution policy key: assignee" in rendered
    assert "owner metadata: planner@example.com" in rendered
    assert "assignee state: atelier/worker/codex/p100 (role: worker)" in rendered
    assert "executable ownership is assigned via assignee atelier/worker/codex/p100" in rendered


def test_render_issue_ownership_explains_deferred_unassigned_case() -> None:
    module = _load_script()
    issue = {
        "id": "at-2",
        "title": "Still deferred",
        "status": "deferred",
        "labels": ["at:epic"],
        "owner": "planner@example.com",
    }

    summary = module.planner_issue_ownership.summarize_issue_ownership(issue)
    rendered = module.planner_issue_ownership.render_issue_ownership(summary)

    assert summary.assignee is None
    assert "assignee state: unassigned (role: none)" in rendered
    assert "deferred work has no active execution owner" in rendered
    assert "check assignee rather than owner metadata" in rendered


def test_render_issue_ownership_marks_planner_assignee_violation() -> None:
    module = _load_script()
    issue = {
        "id": "at-3",
        "title": "Planner accidentally claimed work",
        "status": "open",
        "labels": ["at:epic"],
        "owner": "planner@example.com",
        "assignee": "atelier/planner/codex/p200",
    }

    summary = module.planner_issue_ownership.summarize_issue_ownership(issue)
    rendered = module.planner_issue_ownership.render_issue_ownership(summary)

    assert summary.assignee_role == "planner"
    assert "policy violation: executable work is assigned to planner" in rendered


def test_main_json_emits_summary_payload(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_script()
    beads_root = tmp_path / "beads"
    beads_root.mkdir()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (beads_root, Path("/repo"), "warning: override mismatch"),
    )
    monkeypatch.setattr(
        module,
        "_load_issue",
        lambda **_kwargs: {
            "id": "at-9",
            "title": "JSON output",
            "status": "blocked",
            "labels": ["at:epic"],
            "owner": "planner@example.com",
            "assignee": "atelier/worker/codex/p900",
        },
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["check_issue_ownership.py", "at-9", "--json"],
    )

    module.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "warning: override mismatch" in captured.err
    assert payload["issue_id"] == "at-9"
    assert payload["execution_policy_key"] == "assignee"
    assert payload["assignee_role"] == "worker"


def test_load_issue_uses_store_changeset_shape(monkeypatch) -> None:
    module = _load_script()
    client, _store = build_in_memory_beads_client(
        issues=(
            BUILDER.issue(
                "at-epic",
                title="Epic",
                issue_type="epic",
                labels=("at:epic",),
                status="open",
            ),
            BUILDER.issue(
                "at-epic.1",
                title="Changeset",
                parent="at-epic",
                status="in_progress",
                assignee="atelier/worker/codex/p100",
            ),
        )
    )
    monkeypatch.setattr(
        module,
        "build_atelier_store",
        lambda **_kwargs: build_atelier_store(beads=client),
    )

    issue = module._load_issue(
        issue_id="at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert issue == {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "assignee": "atelier/worker/codex/p100",
        "parent_id": "at-epic",
    }
