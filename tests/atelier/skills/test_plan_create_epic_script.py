from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "plan-create-epic"
        / "scripts"
        / "create_epic.py"
    )
    spec = importlib.util.spec_from_file_location("create_epic_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_create_epic_defaults_to_deferred_status(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )

    monkeypatch.setattr(module.auto_export, "resolve_auto_export_context", lambda: context)

    def fake_run_bd(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="at-epic-1\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.beads, "run_bd_command", fake_run_bd)
    monkeypatch.setattr(
        module.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: module.auto_export.AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=None,
            message="auto-export disabled for test",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "Lifecycle migration",
            "--scope",
            "Move readiness semantics to deferred/open statuses.",
            "--acceptance",
            "Planner transitions use status-only lifecycle.",
        ],
    )

    module.main()

    assert commands[0][0] == "create"
    assert "--type" in commands[0]
    assert commands[0][commands[0].index("--type") + 1] == "epic"
    assert "--label" in commands[0]
    assert "at:epic" in commands[0]
    assert commands[1] == ["update", "at-epic-1", "--status", "deferred"]


def test_create_epic_fails_closed_when_deferred_update_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    export_calls: list[str] = []
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )

    monkeypatch.setattr(module.auto_export, "resolve_auto_export_context", lambda: context)

    def fake_run_bd(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="at-epic-1\n",
                stderr="",
            )
        if args[:3] == ["update", "at-epic-1", "--status"]:
            assert allow_failure is True
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="simulated update failure",
            )
        if args[:2] == ["close", "at-epic-1"]:
            assert allow_failure is True
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="closed",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.beads, "run_bd_command", fake_run_bd)
    monkeypatch.setattr(
        module.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: export_calls.append(issue_id),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "Lifecycle migration",
            "--scope",
            "Move readiness semantics to deferred/open statuses.",
            "--acceptance",
            "Planner transitions use status-only lifecycle.",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert commands[0][0] == "create"
    assert commands[1] == ["update", "at-epic-1", "--status", "deferred"]
    assert commands[2] == ["update", "at-epic-1", "--status", "deferred"]
    assert commands[3] == [
        "close",
        "at-epic-1",
        "--reason",
        "automatic fail-closed: unable to set deferred status after create",
    ]
    assert export_calls == []
