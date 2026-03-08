from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _copy_script(
    tmp_path: Path,
    *,
    skill_name: str,
    script_name: str,
) -> tuple[Path, Path]:
    source_script = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / skill_name
        / "scripts"
        / script_name
    )
    agent_home = tmp_path / "agent-home"
    script_dir = agent_home / "skills" / skill_name / "scripts"
    script_dir.mkdir(parents=True)
    projected_script = script_dir / script_name
    projected_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    return agent_home, projected_script


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
    _write_fake_module(package_root / "__init__.py", "")
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
                "class _Context:\n"
                "    def __init__(self, repo_dir):\n"
                "        self.beads_root = repo_dir\n"
                "        self.repo_root = repo_dir\n"
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
