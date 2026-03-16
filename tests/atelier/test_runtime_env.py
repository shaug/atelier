from __future__ import annotations

import types
from pathlib import Path

import pytest

from atelier import runtime_env


def test_sanitize_subprocess_environment_drops_runtime_routing_keys() -> None:
    env, removed = runtime_env.sanitize_subprocess_environment(
        base_env={
            "ATELIER_PROJECT": "/tmp/other",
            "ATELIER_WORKSPACE": "other/workspace",
            "ATELIER_MODE": "auto",
            "ATELIER_WORK_AGENT_TRACE": "1",
            "PATH": "/usr/bin",
        }
    )

    assert "ATELIER_PROJECT" not in env
    assert "ATELIER_WORKSPACE" not in env
    assert env["ATELIER_MODE"] == "auto"
    assert env["ATELIER_WORK_AGENT_TRACE"] == "1"
    assert env["PATH"] == "/usr/bin"
    assert removed == ("ATELIER_PROJECT", "ATELIER_WORKSPACE")


def test_projected_runtime_contract_prefers_repo_source_when_repo_root_is_known() -> None:
    contract = runtime_env.projected_runtime_contract(repo_root=Path("/repo"))

    assert contract.supported_modes == (
        runtime_env.ProjectedRuntimeMode.REPO_SOURCE,
        runtime_env.ProjectedRuntimeMode.ACTIVE_INTERPRETER,
    )
    assert contract.preferred_mode is runtime_env.ProjectedRuntimeMode.REPO_SOURCE
    assert "src/atelier" in contract.repo_root_behavior
    assert any("--repo-dir" in rule for rule in contract.provenance_selection_rules)
    assert any("transitive dependencies" in rule for rule in contract.provenance_selection_rules)
    assert any("selected runtime" in rule for rule in contract.inherited_pythonpath_rules)
    assert any(
        "repo-source mode is selected" in rule for rule in contract.inherited_pythonpath_rules
    )


def test_projected_runtime_contract_makes_repo_root_none_behavior_explicit() -> None:
    contract = runtime_env.projected_runtime_contract(repo_root=None)

    assert contract.preferred_mode is runtime_env.ProjectedRuntimeMode.ACTIVE_INTERPRETER
    assert "repo_root is None" in contract.repo_root_behavior
    assert "skip repo-runtime re-exec" in contract.repo_root_behavior
    assert any(
        "remain in active-interpreter mode" in rule for rule in contract.provenance_selection_rules
    )
    assert any(
        "active-interpreter mode is selected" in rule
        for rule in contract.inherited_pythonpath_rules
    )
    assert any(
        "ambient PYTHONPATH as healthy" in rule for rule in contract.inherited_pythonpath_rules
    )


def test_format_ambient_env_warning_returns_none_when_no_keys() -> None:
    assert runtime_env.format_ambient_env_warning(()) is None


def test_format_ambient_env_warning_includes_removed_keys_and_migration_guidance() -> None:
    warning = runtime_env.format_ambient_env_warning(("ATELIER_PROJECT", "ATELIER_WORKSPACE"))

    assert warning is not None
    assert "ATELIER_PROJECT" in warning
    assert "ATELIER_WORKSPACE" in warning
    assert "--repo-dir" in warning
    assert "./worktree" in warning


def test_sanitize_pythonpath_environment_drops_inherited_entries() -> None:
    env, removed = runtime_env.sanitize_pythonpath_environment(
        base_env={
            "PYTHONPATH": "/tmp/one:/tmp/two",
            "PATH": "/usr/bin",
        }
    )

    assert "PYTHONPATH" not in env
    assert env["PATH"] == "/usr/bin"
    assert removed == ("/tmp/one", "/tmp/two")


def test_format_ambient_pythonpath_warning_includes_removed_entries() -> None:
    warning = runtime_env.format_ambient_pythonpath_warning(("/tmp/one", "/tmp/two"))

    assert warning is not None
    assert "/tmp/one" in warning
    assert "/tmp/two" in warning
    assert "selected-runtime import roots" in warning


def test_selected_runtime_pythonpath_entries_preserves_loaded_module_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    atelier_module = types.ModuleType("atelier")
    atelier_module.__file__ = "/tmp/tool-runtime/atelier/__init__.py"
    runtime_module = types.ModuleType("atelier.runtime_env")
    runtime_module.__file__ = "/tmp/tool-runtime/atelier/runtime_env.py"
    pydantic_module = types.ModuleType("pydantic")
    pydantic_module.__file__ = "/tmp/tool-runtime/pydantic/__init__.py"
    pydantic_core_module = types.ModuleType("pydantic_core")
    pydantic_core_module.__file__ = "/tmp/tool-extensions/pydantic_core/__init__.py"

    monkeypatch.setitem(runtime_env.sys.modules, "atelier", atelier_module)
    monkeypatch.setitem(runtime_env.sys.modules, "atelier.runtime_env", runtime_module)
    monkeypatch.setitem(runtime_env.sys.modules, "pydantic", pydantic_module)
    monkeypatch.setitem(runtime_env.sys.modules, "pydantic_core", pydantic_core_module)
    rich_module = types.ModuleType("rich")
    rich_module.__file__ = "/tmp/tool-ui/rich/__init__.py"
    monkeypatch.setitem(runtime_env.sys.modules, "rich", rich_module)

    preserved = runtime_env.selected_runtime_pythonpath_entries(
        (
            "/tmp/foreign",
            "/tmp/tool-runtime",
            "/tmp/tool-extensions",
            "/tmp/tool-ui",
        )
    )

    assert preserved == (
        "/tmp/tool-runtime",
        "/tmp/tool-extensions",
        "/tmp/tool-ui",
    )


def test_sanitize_subprocess_environment_empty_mapping_does_not_inherit_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_PROJECT", "/tmp/ambient")
    monkeypatch.setenv("ATELIER_WORKSPACE", "ambient/workspace")
    monkeypatch.setenv("PATH", "/usr/bin")

    env, removed = runtime_env.sanitize_subprocess_environment(base_env={})

    assert env == {}
    assert removed == ()


def test_projected_repo_python_command_prefers_repo_venv_python(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    python_path = repo_root / ".venv" / "bin" / "python3"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_path.chmod(python_path.stat().st_mode | 0o111)

    command = runtime_env.projected_repo_python_command(
        repo_root=repo_root,
        current_executable="/usr/bin/python3",
    )

    assert command == (str(python_path),)


def test_projected_repo_python_command_returns_none_when_current_matches_repo_venv(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    python_path = repo_root / ".venv" / "bin" / "python3"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_path.chmod(python_path.stat().st_mode | 0o111)

    command = runtime_env.projected_repo_python_command(
        repo_root=repo_root,
        current_executable=str(python_path),
    )

    assert command is None


def test_projected_repo_python_command_does_not_treat_base_python_as_repo_venv(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    python_path = repo_root / ".venv" / "bin" / "python3"
    python_path.parent.mkdir(parents=True)
    target = tmp_path / "python3"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | 0o111)
    python_path.symlink_to(target)

    command = runtime_env.projected_repo_python_command(
        repo_root=repo_root,
        current_executable=str(target),
    )

    assert command == (str(python_path),)


def test_collect_projected_bootstrap_diagnostics_reports_repo_root_none_state() -> None:
    diagnostics = runtime_env.collect_projected_bootstrap_diagnostics(
        repo_root=None,
        script_path=Path("/tmp/projected.py"),
        current_executable="/usr/bin/python3",
        removed_pythonpath_entries=("/tmp/foreign/site-packages",),
    )

    assert diagnostics.selected_mode is runtime_env.ProjectedRuntimeMode.ACTIVE_INTERPRETER
    assert diagnostics.repo_runtime_status == "not-applicable"
    assert "repo_root is unresolved" in diagnostics.repo_runtime_detail
    assert diagnostics.removed_pythonpath_entries == ("/tmp/foreign/site-packages",)
    assert diagnostics.preserved_pythonpath_entries == ()


def test_maybe_reexec_projected_repo_runtime_does_not_select_repo_runtime_without_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _unexpected_repo_command(**_kwargs: object) -> tuple[str, ...] | None:
        nonlocal called
        called = True
        return ("python3",)

    monkeypatch.setattr(
        runtime_env,
        "projected_repo_python_command",
        _unexpected_repo_command,
    )

    runtime_env.maybe_reexec_projected_repo_runtime(
        repo_root=None,
        script_path=Path("/tmp/projected.py"),
    )

    assert called is False


def test_ensure_projected_runtime_dependency_returns_when_import_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []

    def _fake_import_module(name: str):
        imported.append(name)
        return object()

    monkeypatch.setattr(runtime_env.importlib, "import_module", _fake_import_module)

    preserved = runtime_env.ensure_projected_runtime_dependency(
        repo_root=Path("/repo"),
        script_path=Path("/repo/skills/example.py"),
    )

    assert imported == [
        "pydantic",
        "pydantic_core",
        "pydantic_core._pydantic_core",
    ]
    assert preserved == ()


def test_ensure_projected_runtime_dependency_preserves_split_tool_runtime_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_files = {
        "pydantic": "/tmp/tool-runtime/pydantic/__init__.py",
        "pydantic_core": "/tmp/tool-runtime/pydantic_core/__init__.py",
        "pydantic_core._pydantic_core": ("/tmp/tool-runtime/pydantic_core/_pydantic_core.so"),
        "platformdirs": "/tmp/tool-runtime/platformdirs/__init__.py",
        "questionary": "/tmp/tool-runtime/questionary/__init__.py",
        "rich": "/tmp/tool-ui/rich/__init__.py",
        "typer": "/tmp/tool-runtime/typer/__init__.py",
    }

    class _FakeModule:
        def __init__(self, module_file: str) -> None:
            self.__file__ = module_file

    def _fake_import_module(name: str) -> object:
        module = _FakeModule(module_files[name])
        monkeypatch.setitem(runtime_env.sys.modules, name, module)
        return module

    monkeypatch.setattr(runtime_env.importlib, "import_module", _fake_import_module)
    monkeypatch.setenv(
        "PYTHONPATH",
        "/tmp/tool-runtime:/tmp/tool-ui",
    )

    preserved = runtime_env.ensure_projected_runtime_dependency(
        repo_root=None,
        script_path=Path("/tmp/agent-home/skills/example.py"),
    )

    assert preserved == (
        "/tmp/tool-runtime",
        "/tmp/tool-ui",
    )


def test_ensure_projected_runtime_dependency_fails_closed_for_provenance_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FakeModule:
        def __init__(self, module_file: str) -> None:
            self.__file__ = module_file

    module_map = {
        "pydantic": _FakeModule("/tmp/foreign/pydantic/__init__.py"),
        "pydantic_core": _FakeModule(
            "/repo/.venv/lib/python3.11/site-packages/pydantic_core/__init__.py"
        ),
        "pydantic_core._pydantic_core": _FakeModule(
            "/repo/.venv/lib/python3.11/site-packages/pydantic_core/_pydantic_core.so"
        ),
    }

    monkeypatch.setattr(
        runtime_env.importlib,
        "import_module",
        lambda name: module_map[name],
    )
    monkeypatch.setattr(
        runtime_env.sysconfig,
        "get_path",
        lambda key: {
            "purelib": "/repo/.venv/lib/python3.11/site-packages",
            "platlib": "/repo/.venv/lib/python3.11/site-packages",
        }[key],
    )
    monkeypatch.setattr(
        runtime_env,
        "_repo_python_candidate",
        lambda _repo_root: Path("/repo/.venv/bin/python3"),
    )

    with pytest.raises(SystemExit) as exc_info:
        runtime_env.ensure_projected_runtime_dependency(
            repo_root=Path("/repo"),
            script_path=Path("/repo/skills/example.py"),
            current_executable="/repo/.venv/bin/python3",
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "runtime provenance is mixed" in captured.err
    assert "module: pydantic" in captured.err
    assert "module_path:" in captured.err
    assert "foreign/pydantic/__init__.py" in captured.err
    assert "selected_mode: repo-source" in captured.err
    assert "repo_runtime_status: active" in captured.err
    assert "expected_roots: /repo/.venv/lib/python3.11/site-packages" in captured.err
    assert "pythonpath_removed: (none)" in captured.err
    assert "pythonpath_preserved: (none)" in captured.err
    assert "dependency provenance contradiction" in captured.err


def test_ensure_projected_runtime_dependency_fails_closed_for_installed_tool_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fake_import_module(_name: str):
        raise ModuleNotFoundError("No module named 'pydantic_core._pydantic_core'")

    monkeypatch.setattr(runtime_env.importlib, "import_module", _fake_import_module)
    monkeypatch.setattr(runtime_env, "projected_repo_python_command", lambda **_kwargs: None)

    with pytest.raises(SystemExit) as exc_info:
        runtime_env.ensure_projected_runtime_dependency(
            repo_root=Path("/repo"),
            script_path=Path(
                "/Users/scott/.local/share/uv/tools/atelier/lib/python3.11/"
                "site-packages/atelier/skills/planner-startup-check/scripts/"
                "refresh_overview.py"
            ),
            current_executable="/Users/scott/.local/share/uv/tools/atelier/bin/python",
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "planner helper runtime is unhealthy" in captured.err
    assert "runtime_provenance: installed-tool" in captured.err
    assert "selected_mode: repo-source" in captured.err
    assert "repo_runtime_status: unavailable" in captured.err
    assert "dependency: pydantic_core._pydantic_core" in captured.err
    assert "pythonpath_removed: (none)" in captured.err
    assert "not another src-path-ordering regression" in captured.err
    assert "repair or reinstall the uv tool environment" in captured.err


def test_ensure_projected_runtime_dependency_guides_repo_hint_when_repo_root_is_unresolved(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fake_import_module(_name: str):
        raise ModuleNotFoundError("No module named 'pydantic_core._pydantic_core'")

    monkeypatch.setattr(runtime_env.importlib, "import_module", _fake_import_module)
    diagnostics = runtime_env.collect_projected_bootstrap_diagnostics(
        repo_root=None,
        script_path=Path("/tmp/projected.py"),
        current_executable="/Users/scott/.local/share/uv/tools/atelier/bin/python",
        removed_pythonpath_entries=("/tmp/foreign/site-packages",),
    )

    with pytest.raises(SystemExit) as exc_info:
        runtime_env.ensure_projected_runtime_dependency(
            repo_root=None,
            script_path=Path("/tmp/projected.py"),
            current_executable="/Users/scott/.local/share/uv/tools/atelier/bin/python",
            bootstrap_diagnostics=diagnostics,
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "selected_mode: active-interpreter" in captured.err
    assert "runtime_provenance: installed-tool" in captured.err
    assert "repo_runtime_status: not-applicable" in captured.err
    assert "pythonpath_removed: /tmp/foreign/site-packages" in captured.err
    assert "pythonpath_preserved: (none)" in captured.err
    assert "tool-installed mode stayed active because repo_root could not be proven" in captured.err
