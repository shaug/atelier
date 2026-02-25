from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_script():
    scripts_dir = Path(__file__).resolve().parents[3] / "src/atelier/skills/epic-list/scripts"
    path = scripts_dir / "list_epics.py"
    spec = importlib.util.spec_from_file_location("test_list_epics_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_status_bucket_marks_open_epic_with_open_dependency_as_blocked() -> None:
    module = _load_script()
    issue = {
        "id": "at-a1",
        "status": "open",
        "labels": ["at:epic", "at:ready"],
        "dependencies": [{"id": "at-dep", "status": "open"}],
    }

    bucket = module._status_bucket(issue, show_drafts=True)

    assert bucket == "blocked"


def test_status_bucket_ignores_closed_dependency_for_open_epic() -> None:
    module = _load_script()
    issue = {
        "id": "at-a1",
        "status": "open",
        "labels": ["at:epic", "at:ready"],
        "dependencies": [{"id": "at-dep", "status": "closed"}],
    }

    bucket = module._status_bucket(issue, show_drafts=True)

    assert bucket == "open"


def test_status_bucket_treats_missing_ready_as_draft() -> None:
    module = _load_script()
    issue = {
        "id": "at-a1",
        "status": "open",
        "labels": ["at:epic"],
    }

    bucket = module._status_bucket(issue, show_drafts=True)

    assert bucket == "draft"


def test_render_epics_includes_blocker_list_for_blocked_bucket() -> None:
    module = _load_script()
    blocked = {
        "id": "at-xfw",
        "title": "Channel URL input does not work",
        "status": "open",
        "labels": ["at:epic", "at:ready"],
        "description": "workspace.root_branch: test-branch",
        "dependencies": [{"id": "at-u9j", "status": "in_progress"}],
    }

    rendered = module._render_epics([blocked], show_drafts=True)

    assert "Blocked epics:" in rendered
    assert "at-xfw [open] Channel URL input does not work" in rendered
    assert "blockers: at-u9j [in_progress]" in rendered


def test_run_bd_list_defaults_to_direct_mode(monkeypatch) -> None:
    module = _load_script()
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    issues = module._run_bd_list(None)

    assert issues == []
    assert captured["command"] == ["bd", "list", "--label", "at:epic", "--json"]
