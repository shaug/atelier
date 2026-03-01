from __future__ import annotations

import importlib.util
import json
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
        / "plan-changesets"
        / "scripts"
        / "create_changeset.py"
    )
    spec = importlib.util.spec_from_file_location("create_changeset_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configure_script_mocks(module, monkeypatch, tmp_path: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    list_calls = 0
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
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            if list_calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='[{"id":"at-122"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='[{"id":"at-122"},{"id":"at-123"}]',
                stderr="",
            )
        if args and args[0] == "create":
            assert allow_failure is False
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="at-123\n", stderr=""
            )
        if args[:3] == ["update", "at-123", "--status"]:
            assert allow_failure is True
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
    return commands


def test_create_changeset_defaults_to_deferred_status(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    commands = _configure_script_mocks(module, monkeypatch, tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Draft changeset",
            "--acceptance",
            "Acceptance text",
        ],
    )

    module.main()

    create_command = next(command for command in commands if command and command[0] == "create")
    status_commands = [
        command for command in commands if command[:3] == ["update", "at-123", "--status"]
    ]
    assert create_command[:2] == ["create", "--parent"]
    assert "cs:planned" not in create_command
    assert "cs:ready" not in create_command
    assert status_commands == [["update", "at-123", "--status", "deferred"]]


def test_create_changeset_accepts_open_status_override(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    commands = _configure_script_mocks(module, monkeypatch, tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Ready changeset",
            "--acceptance",
            "Acceptance text",
            "--status",
            "open",
        ],
    )

    module.main()

    create_command = next(command for command in commands if command and command[0] == "create")
    status_commands = [
        command for command in commands if command[:3] == ["update", "at-123", "--status"]
    ]
    assert "cs:ready" not in create_command
    assert status_commands == [["update", "at-123", "--status", "open"]]


def test_create_changeset_fails_closed_when_deferred_update_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    list_calls = 0
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
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            if list_calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='[{"id":"at-122"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='[{"id":"at-122"},{"id":"at-123"}]',
                stderr="",
            )
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="at-123\n",
                stderr="",
            )
        if args[:3] == ["update", "at-123", "--status"]:
            assert allow_failure is True
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="simulated update failure",
            )
        if args[:2] == ["close", "at-123"]:
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Draft changeset",
            "--acceptance",
            "Acceptance text",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert commands[1][0] == "create"
    assert commands[3] == ["update", "at-123", "--status", "deferred"]
    assert commands[4] == ["update", "at-123", "--status", "deferred"]
    assert commands[5] == [
        "close",
        "at-123",
        "--reason",
        "automatic fail-closed: unable to set deferred status after create",
    ]
    assert export_calls == []


def test_create_changeset_uses_new_child_id_when_create_output_is_noisy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    list_calls = 0
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
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            if list_calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='[{"id":"at-200"},{"id":"at-201"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='[{"id":"at-200"},{"id":"at-201"},{"id":"at-202"}]',
                stderr="",
            )
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="warning: previous changeset at-201 remains open\nat-202\n",
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Noisy create output",
            "--acceptance",
            "Acceptance text",
        ],
    )

    module.main()

    status_commands = [
        command for command in commands if command[:3] == ["update", "at-202", "--status"]
    ]
    assert status_commands == [["update", "at-202", "--status", "deferred"]]


def test_create_changeset_lists_all_children_for_large_epic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    list_calls = 0
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )
    existing_ids = [f"at-{index}" for index in range(200, 255)]
    created_id = "at-255"

    monkeypatch.setattr(module.auto_export, "resolve_auto_export_context", lambda: context)

    def fake_run_bd(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            ids = existing_ids if list_calls == 1 else [*existing_ids, created_id]
            has_unbounded_limit = False
            if "--limit" in args:
                limit_index = args.index("--limit")
                has_unbounded_limit = limit_index + 1 < len(args) and args[limit_index + 1] == "0"
            if not has_unbounded_limit:
                ids = ids[:50]
            payload = json.dumps([{"id": issue_id} for issue_id in ids])
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=payload,
                stderr="",
            )
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"warning: existing {existing_ids[-1]} still open\n{created_id}\n",
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Large epic create output",
            "--acceptance",
            "Acceptance text",
        ],
    )

    module.main()

    list_commands = [command for command in commands if command[:2] == ["list", "--parent"]]
    status_commands = [
        command for command in commands if command[:3] == ["update", created_id, "--status"]
    ]
    assert len(list_commands) == 2
    assert all(
        "--limit" in command and command[command.index("--limit") + 1] == "0"
        for command in list_commands
    )
    assert status_commands == [["update", created_id, "--status", "deferred"]]


def test_create_changeset_fails_when_create_does_not_add_new_child(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    list_calls = 0
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
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='[{"id":"at-200"},{"id":"at-201"}]',
                stderr="",
            )
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="at-201\n",
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "No new child created",
            "--acceptance",
            "Acceptance text",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "create output excerpt" in captured.err
    assert "stdout='at-201'" in captured.err
    assert "stderr='<empty>'" in captured.err
    assert all(not (command and command[0] == "update") for command in commands)
    assert all(not (command and command[0] == "close") for command in commands)
    assert export_calls == []


def test_create_changeset_fails_when_create_adds_multiple_new_children(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    list_calls = 0
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
        nonlocal list_calls
        commands.append(args)
        assert beads_root == context.beads_root
        assert cwd == context.project_dir
        if args[:2] == ["list", "--parent"]:
            list_calls += 1
            if list_calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='[{"id":"at-200"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='[{"id":"at-200"},{"id":"at-201"},{"id":"at-202"}]',
                stderr="",
            )
        if args and args[0] == "create":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="created changesets",
                stderr="warning: duplicate create output",
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Ambiguous new children",
            "--acceptance",
            "Acceptance text",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "ambiguous child ids" in captured.err
    assert "at-201, at-202" in captured.err
    assert "create output excerpt" in captured.err
    assert "stdout='created changesets'" in captured.err
    assert "stderr='warning: duplicate create output'" in captured.err
    assert all(not (command and command[0] == "update") for command in commands)
    assert all(not (command and command[0] == "close") for command in commands)
    assert export_calls == []
