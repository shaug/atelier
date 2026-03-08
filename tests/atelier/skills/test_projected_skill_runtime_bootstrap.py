from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _copy_script(
    tmp_path: Path,
    *,
    skill_name: str,
    script_name: str,
) -> tuple[Path, Path]:
    agent_home = tmp_path / "agent-home"
    projected_script = _copy_script_into_agent_home(
        agent_home,
        skill_name=skill_name,
        script_name=script_name,
    )
    return agent_home, projected_script


def _copy_script_into_agent_home(
    agent_home: Path,
    *,
    skill_name: str,
    script_name: str,
) -> Path:
    source_script = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / skill_name
        / "scripts"
        / script_name
    )
    script_dir = agent_home / "skills" / skill_name / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    projected_script = script_dir / script_name
    projected_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    return projected_script


def _write_fake_module(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fake_repo(
    tmp_path: Path,
    *,
    sentinel_import: str,
    extra_modules: dict[str, str] | None = None,
) -> Path:
    repo_root = tmp_path / "repo"
    package_root = repo_root / "src" / "atelier"
    source_root = Path(__file__).resolve().parents[3] / "src" / "atelier"
    _write_fake_module(package_root / "__init__.py", "")
    _write_fake_module(
        package_root / "runtime_env.py",
        (source_root / "runtime_env.py").read_text(encoding="utf-8"),
    )
    _write_fake_module(
        package_root / f"{sentinel_import}.py",
        "\n".join(
            [
                "from pathlib import Path",
                "import os",
                "",
                "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')",
                "",
            ]
        ),
    )
    _write_fake_module(package_root / "beads.py", "")
    _write_fake_module(
        package_root / "beads_context.py",
        "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
        "    return (repo_dir, None)\n",
    )
    _write_fake_module(
        package_root / "executable_work_validation.py",
        "def compact_excerpt(value):\n"
        "    return str(value)\n"
        "def validate_executable_work_payload(**_kwargs):\n"
        "    return []\n",
    )
    for module_name, content in (extra_modules or {}).items():
        _write_fake_module(package_root / module_name, content)
    return repo_root


def _fake_installed_package(tmp_path: Path, *, modules: dict[str, str]) -> Path:
    installed_root = tmp_path / "installed"
    package_root = installed_root / "atelier"
    _write_fake_module(package_root / "__init__.py", "")
    for module_name, content in modules.items():
        _write_fake_module(package_root / module_name, content)
    return installed_root


def _link_repo_python(repo_root: Path) -> None:
    repo_python = repo_root / ".venv" / "bin" / "python3"
    repo_python.parent.mkdir(parents=True, exist_ok=True)
    repo_python.symlink_to(Path(sys.executable).resolve())


def _write_repo_python_without_site_packages(repo_root: Path) -> None:
    repo_python = repo_root / ".venv" / "bin" / "python3"
    repo_python.parent.mkdir(parents=True, exist_ok=True)
    repo_python.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f'exec {Path(sys.executable).resolve()} -S "$@"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repo_python.chmod(repo_python.stat().st_mode | 0o111)


def _ambient_python_executable() -> str:
    current = Path(sys.executable).resolve()
    candidates = (
        "/opt/homebrew/opt/python@3.14/bin/python3.14",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        shutil.which("python3", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
    )
    for raw_candidate in candidates:
        if not raw_candidate:
            continue
        candidate = Path(raw_candidate)
        if not candidate.is_file():
            continue
        try:
            if candidate.resolve() == current:
                continue
        except OSError:
            continue
        version_probe = subprocess.run(
            [str(candidate), "-c", "import sys; print(sys.version_info[:2] >= (3, 10))"],
            check=False,
            capture_output=True,
            text=True,
        )
        if version_probe.returncode == 0 and version_probe.stdout.strip() == "True":
            return str(candidate)
    pytest.skip("no distinct Python 3.10+ executable available for projected-runtime test")


def test_projected_create_epic_prefers_agent_worktree_source(tmp_path: Path) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="plan-create-epic",
        script_name="create_epic.py",
    )
    repo_root = _fake_repo(tmp_path, sentinel_import="auto_export")
    (agent_home / "worktree").symlink_to(repo_root)
    sentinel_path = tmp_path / "create-epic-sentinel.txt"

    completed = subprocess.run(
        [sys.executable, str(projected_script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "BOOTSTRAP_SENTINEL": str(sentinel_path),
        },
    )

    assert completed.returncode == 0
    assert sentinel_path.read_text(encoding="utf-8") == str(
        repo_root / "src" / "atelier" / "auto_export.py"
    )


def test_projected_create_epic_reorders_repo_src_ahead_of_installed_package(
    tmp_path: Path,
) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="plan-create-epic",
        script_name="create_epic.py",
    )
    repo_root = _fake_repo(tmp_path, sentinel_import="auto_export")
    installed_root = _fake_installed_package(
        tmp_path,
        modules={
            "auto_export.py": (
                "from pathlib import Path\n"
                "import os\n"
                "\n"
                "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')\n"
            ),
            "beads.py": "",
            "beads_context.py": (
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
            ),
            "executable_work_validation.py": (
                "def compact_excerpt(value):\n"
                "    return str(value)\n"
                "def validate_executable_work_payload(**_kwargs):\n"
                "    return []\n"
            ),
        },
    )
    sentinel_path = tmp_path / "create-epic-reorder-sentinel.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(projected_script),
            "--repo-dir",
            str(repo_root),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "BOOTSTRAP_SENTINEL": str(sentinel_path),
            "PYTHONPATH": os.pathsep.join([str(installed_root), str(repo_root / "src")]),
        },
    )

    assert completed.returncode == 0
    assert sentinel_path.read_text(encoding="utf-8") == str(
        repo_root / "src" / "atelier" / "auto_export.py"
    )


def test_projected_auto_export_prefers_explicit_repo_dir_source(tmp_path: Path) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="tickets",
        script_name="auto_export_issue.py",
    )
    repo_root = _fake_repo(tmp_path, sentinel_import="auto_export")
    sentinel_path = tmp_path / "auto-export-sentinel.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(projected_script),
            "--repo-dir",
            str(repo_root),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "BOOTSTRAP_SENTINEL": str(sentinel_path),
        },
    )

    assert completed.returncode == 0
    assert sentinel_path.read_text(encoding="utf-8") == str(
        repo_root / "src" / "atelier" / "auto_export.py"
    )


def test_projected_check_guardrails_reorders_repo_src_ahead_of_installed_package(
    tmp_path: Path,
) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="plan-changeset-guardrails",
        script_name="check_guardrails.py",
    )
    repo_root = _fake_repo(
        tmp_path,
        sentinel_import="beads",
        extra_modules={
            "bd_invocation.py": (
                "def with_bd_mode(*args, beads_dir=None, env=None):\n    return ['bd', *args]\n"
            ),
            "beads_context.py": (
                "from pathlib import Path\n"
                "import os\n"
                "\n"
                "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')\n"
                "\n"
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
            ),
            "planner_contract.py": (
                "def validate_authoring_contract(*_args, **_kwargs):\n    return []\n"
            ),
        },
    )
    installed_root = _fake_installed_package(
        tmp_path,
        modules={
            "beads.py": (
                "from pathlib import Path\n"
                "import os\n"
                "\n"
                "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')\n"
            ),
            "bd_invocation.py": (
                "def with_bd_mode(*args, beads_dir=None, env=None):\n"
                "    return ['installed', *args]\n"
            ),
            "beads_context.py": (
                "from pathlib import Path\n"
                "import os\n"
                "\n"
                "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')\n"
                "\n"
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
            ),
            "planner_contract.py": (
                "def validate_authoring_contract(*_args, **_kwargs):\n    return []\n"
            ),
        },
    )
    sentinel_path = tmp_path / "check-guardrails-sentinel.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(projected_script),
            "--repo-dir",
            str(repo_root),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "BOOTSTRAP_SENTINEL": str(sentinel_path),
            "PYTHONPATH": os.pathsep.join([str(installed_root), str(repo_root / "src")]),
        },
    )

    assert completed.returncode == 0
    assert sentinel_path.read_text(encoding="utf-8") == str(
        repo_root / "src" / "atelier" / "beads_context.py"
    )


def test_projected_refresh_overview_reorders_repo_src_ahead_of_installed_package(
    tmp_path: Path,
) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="planner-startup-check",
        script_name="refresh_overview.py",
    )
    repo_root = _fake_repo(
        tmp_path,
        sentinel_import="planner_startup_check",
        extra_modules={
            "lifecycle.py": "",
            "planner_overview.py": "",
            "beads_context.py": (
                "from pathlib import Path\n"
                "\n"
                "class _Context:\n"
                "    def __init__(self, repo_dir):\n"
                "        resolved = Path(repo_dir)\n"
                "        self.beads_root = resolved\n"
                "        self.repo_root = resolved\n"
                "        self.override_warning = None\n"
                "\n"
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
                "\n"
                "def resolve_skill_beads_context(*, beads_dir=None, repo_dir=None):\n"
                "    return _Context(repo_dir)\n"
            ),
            "planner_startup_check.py": "\n".join(
                [
                    "from dataclasses import dataclass",
                    "from pathlib import Path",
                    "import os",
                    "",
                    "Path(os.environ['BOOTSTRAP_SENTINEL']).write_text(__file__, encoding='utf-8')",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupBeadsInvocationHelper:",
                    "    beads_root: object | None = None",
                    "    cwd: object | None = None",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupCommandResult:",
                    "    inbox_messages: tuple[object, ...] = ()",
                    "    queued_messages: tuple[object, ...] = ()",
                    "    epics: tuple[object, ...] = ()",
                    "    parity_report: object | None = None",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupRuntimePreflight:",
                    "    name: str",
                    "    status: str",
                    "    detail: str",
                    "",
                    "def build_startup_triage_failure_model(**_kwargs):",
                    "    return None",
                    "",
                    "def build_startup_triage_model(**_kwargs):",
                    "    return None",
                    "",
                    "def execute_startup_command_plan(*_args, **_kwargs):",
                    "    return StartupCommandResult()",
                    "",
                    "def render_startup_triage_markdown(*_args, **_kwargs):",
                    "    return ''",
                ]
            ),
        },
    )
    installed_root = _fake_installed_package(
        tmp_path,
        modules={
            "lifecycle.py": "",
            "planner_overview.py": "",
            "beads_context.py": (
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
                "\n"
                "class _Context:\n"
                "    def __init__(self, repo_dir):\n"
                "        self.beads_root = repo_dir\n"
                "        self.repo_root = repo_dir\n"
                "        self.override_warning = None\n"
                "\n"
                "def resolve_skill_beads_context(*, beads_dir=None, repo_dir=None):\n"
                "    return _Context(repo_dir)\n"
            ),
            "planner_startup_check.py": "\n".join(
                [
                    "class StartupBeadsInvocationHelper:",
                    "    pass",
                    "",
                    "class StartupCommandResult:",
                    "    pass",
                    "",
                    "def build_startup_triage_failure_model(**_kwargs):",
                    "    return None",
                    "",
                    "def build_startup_triage_model(**_kwargs):",
                    "    return None",
                    "",
                    "def execute_startup_command_plan(*_args, **_kwargs):",
                    "    return StartupCommandResult()",
                    "",
                    "def render_startup_triage_markdown(*_args, **_kwargs):",
                    "    return ''",
                ]
            ),
        },
    )
    sentinel_path = tmp_path / "refresh-overview-sentinel.txt"

    completed = subprocess.run(
        [
            sys.executable,
            str(projected_script),
            "--repo-dir",
            str(repo_root),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "BOOTSTRAP_SENTINEL": str(sentinel_path),
            "PYTHONPATH": os.pathsep.join([str(installed_root), str(repo_root / "src")]),
        },
    )

    assert completed.returncode == 0
    assert sentinel_path.read_text(encoding="utf-8") == str(
        repo_root / "src" / "atelier" / "planner_startup_check.py"
    )


def test_projected_refresh_overview_fails_closed_when_repo_runtime_is_dependency_unhealthy(
    tmp_path: Path,
) -> None:
    agent_home, projected_script = _copy_script(
        tmp_path,
        skill_name="planner-startup-check",
        script_name="refresh_overview.py",
    )
    _copy_script_into_agent_home(
        agent_home,
        skill_name="plan-create-epic",
        script_name="create_epic.py",
    )
    _copy_script_into_agent_home(
        agent_home,
        skill_name="tickets",
        script_name="auto_export_issue.py",
    )
    repo_root = _fake_repo(
        tmp_path,
        sentinel_import="bootstrap_marker",
        extra_modules={
            "auto_export.py": "\n".join(
                [
                    "from pathlib import Path",
                    "import os",
                    "import sys",
                    "",
                    "Path(os.environ['AUTO_EXPORT_SENTINEL']).write_text(",
                    "    sys.executable,",
                    "    encoding='utf-8',",
                    ")",
                    "",
                    "def resolve_auto_export_context(*_args, **_kwargs):",
                    "    return None",
                    "",
                    "def auto_export_issue(*_args, **_kwargs):",
                    "    return None",
                ]
            ),
            "lifecycle.py": (
                "def canonical_lifecycle_status(value):\n    return str(value or '').strip()\n"
            ),
            "planner_overview.py": (
                "def render_epics(*_args, **_kwargs):\n    return 'Epics by state:\\n- (none)'\n"
            ),
            "beads_context.py": (
                "from pathlib import Path\n"
                "\n"
                "class _Context:\n"
                "    def __init__(self, repo_dir):\n"
                "        resolved = Path(repo_dir)\n"
                "        self.beads_root = resolved\n"
                "        self.repo_root = resolved\n"
                "        self.override_warning = None\n"
                "\n"
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
                "\n"
                "def resolve_skill_beads_context(*, beads_dir=None, repo_dir=None):\n"
                "    return _Context(repo_dir)\n"
            ),
            "planner_startup_check.py": "\n".join(
                [
                    "from dataclasses import dataclass",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupBeadsInvocationHelper:",
                    "    beads_root: object | None = None",
                    "    cwd: object | None = None",
                    "",
                    "    def list_descendant_changesets(self, *_args, **_kwargs):",
                    "        return []",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupCommandResult:",
                    "    inbox_messages: tuple[object, ...] = ()",
                    "    queued_messages: tuple[object, ...] = ()",
                    "    epics: tuple[object, ...] = ()",
                    "    parity_report: object | None = None",
                    "",
                    "@dataclass(frozen=True)",
                    "class StartupRuntimePreflight:",
                    "    name: str",
                    "    status: str",
                    "    detail: str",
                    "",
                    "def build_startup_triage_failure_model(**_kwargs):",
                    "    return None",
                    "",
                    "def build_startup_triage_model(**_kwargs):",
                    "    return None",
                    "",
                    "def execute_startup_command_plan(*_args, **_kwargs):",
                    "    return StartupCommandResult()",
                    "",
                    "def render_startup_triage_markdown(*_args, **_kwargs):",
                    "    return 'ok'",
                ]
            ),
        },
    )
    _write_repo_python_without_site_packages(repo_root)
    installed_root = _fake_installed_package(
        tmp_path,
        modules={
            "auto_export.py": (
                "from pathlib import Path\n"
                "import os\n"
                "\n"
                "Path(os.environ['AUTO_EXPORT_SENTINEL']).write_text('installed', encoding='utf-8')\n"
            ),
            "beads.py": "",
            "beads_context.py": (
                "def resolve_runtime_repo_dir_hint(*, repo_dir=None, cwd=None, env=None):\n"
                "    return (repo_dir, None)\n"
                "\n"
                "class _Context:\n"
                "    def __init__(self, repo_dir):\n"
                "        self.beads_root = repo_dir\n"
                "        self.repo_root = repo_dir\n"
                "        self.override_warning = None\n"
                "\n"
                "def resolve_skill_beads_context(*, beads_dir=None, repo_dir=None):\n"
                "    return _Context(repo_dir)\n"
            ),
            "executable_work_validation.py": (
                "def compact_excerpt(value):\n"
                "    return str(value)\n"
                "def validate_executable_work_payload(**_kwargs):\n"
                "    return []\n"
            ),
            "lifecycle.py": (
                "def canonical_lifecycle_status(value):\n    return str(value or '').strip()\n"
            ),
            "planner_overview.py": (
                "def render_epics(*_args, **_kwargs):\n    return 'installed'\n"
            ),
            "planner_startup_check.py": ("class StartupBeadsInvocationHelper:\n    pass\n"),
        },
    )
    ambient_python = _ambient_python_executable()
    sentinel_path = tmp_path / "auto-export-runtime.txt"

    completed = subprocess.run(
        [
            ambient_python,
            str(projected_script),
            "--agent-id",
            "atelier/planner/example",
            "--repo-dir",
            str(repo_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=agent_home,
        env={
            "AUTO_EXPORT_SENTINEL": str(sentinel_path),
            "PYTHONPATH": os.pathsep.join([str(installed_root), str(repo_root / "src")]),
        },
    )

    assert completed.returncode == 1
    assert not sentinel_path.exists()
    assert "planner helper runtime is unhealthy" in completed.stderr
    assert "runtime: ambient" in completed.stderr
    assert "dependency: pydantic_core._pydantic_core" in completed.stderr
    assert "repair the selected repo runtime or rerun explicitly via" in completed.stderr
