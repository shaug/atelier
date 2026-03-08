from __future__ import annotations

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


def _fake_repo(tmp_path: Path, *, sentinel_import: str) -> Path:
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
    return repo_root


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
