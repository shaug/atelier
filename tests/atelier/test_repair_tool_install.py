"""Tests for scripts/repair_tool_install.py."""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_tool_install.py"


def _load_repair_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repair_tool_install", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load repair_tool_install module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def repair_module() -> ModuleType:
    return _load_repair_module()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_launcher(path: Path, interpreter: Path, import_target: str) -> None:
    _write_executable(
        path,
        "\n".join(
            [
                f"#!{interpreter}",
                "import sys",
                f"from {import_target} import main",
                "raise SystemExit(main())",
                "",
            ]
        ),
    )


def test_main_removes_broken_shadowed_launcher(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    repair_module: ModuleType,
) -> None:
    user_base = tmp_path / "user-base"
    desired_dir = user_base / "bin"
    desired_dir.mkdir(parents=True)
    stale_dir = tmp_path / "stale-bin"
    stale_dir.mkdir()

    monkeypatch.setattr(repair_module.site, "USER_BASE", str(user_base))
    monkeypatch.setenv("PATH", os.pathsep.join([str(stale_dir), str(desired_dir)]))

    desired_launcher = desired_dir / "atelier"
    _write_executable(desired_launcher, "#!/bin/sh\nexit 0\n")

    broken_python = stale_dir / "python3.11"
    _write_executable(broken_python, "#!/bin/sh\nexit 1\n")
    stale_launcher = stale_dir / "atelier"
    _write_launcher(stale_launcher, broken_python, "atelier.cli")

    assert repair_module.main(["atelier", "atelier.cli"]) == 0

    assert not stale_launcher.exists()
    assert desired_launcher.exists()
    assert "removed stale launcher" in capsys.readouterr().err


def test_main_keeps_working_shadow_launcher_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    repair_module: ModuleType,
) -> None:
    user_base = tmp_path / "user-base"
    desired_dir = user_base / "bin"
    desired_dir.mkdir(parents=True)
    shadow_dir = tmp_path / "shadow-bin"
    shadow_dir.mkdir()

    monkeypatch.setattr(repair_module.site, "USER_BASE", str(user_base))
    monkeypatch.setenv("PATH", os.pathsep.join([str(shadow_dir), str(desired_dir)]))

    desired_launcher = desired_dir / "atelier"
    _write_executable(desired_launcher, "#!/bin/sh\nexit 0\n")

    working_python = shadow_dir / "python3.11"
    _write_executable(working_python, "#!/bin/sh\nexit 0\n")
    shadow_launcher = shadow_dir / "atelier"
    _write_launcher(shadow_launcher, working_python, "atelier.cli")

    assert repair_module.main(["atelier", "atelier.cli"]) == 0

    assert shadow_launcher.exists()
    assert "shadows" in capsys.readouterr().err


def test_main_ignores_unrelated_path_executable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    repair_module: ModuleType,
) -> None:
    user_base = tmp_path / "user-base"
    desired_dir = user_base / "bin"
    desired_dir.mkdir(parents=True)
    other_dir = tmp_path / "other-bin"
    other_dir.mkdir()

    monkeypatch.setattr(repair_module.site, "USER_BASE", str(user_base))
    monkeypatch.setenv("PATH", os.pathsep.join([str(other_dir), str(desired_dir)]))

    desired_launcher = desired_dir / "atelier"
    _write_executable(desired_launcher, "#!/bin/sh\nexit 0\n")

    other_launcher = other_dir / "atelier"
    _write_executable(other_launcher, "#!/bin/sh\necho unrelated\n")

    assert repair_module.main(["atelier", "atelier.cli"]) == 0

    assert other_launcher.exists()
    assert capsys.readouterr().err == ""
