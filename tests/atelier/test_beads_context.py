from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import atelier.paths as paths
from atelier import beads_context


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _patch_project_resolution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    repo_root: Path,
    project_beads_root: Path,
) -> None:
    monkeypatch.setattr(
        beads_context,
        "resolve_current_project_with_repo_root",
        lambda: (project_root, object(), str(repo_root), repo_root),
    )
    monkeypatch.setattr(
        beads_context.config,
        "resolve_project_data_dir",
        lambda _project_root, _project_config: project_root,
    )
    monkeypatch.setattr(
        beads_context.config,
        "resolve_beads_root",
        lambda _project_dir, _repo_root: project_beads_root,
    )


@pytest.mark.parametrize(
    ("project_has_data", "repo_has_data"),
    [
        (False, True),
        (True, False),
    ],
)
def test_resolve_skill_beads_context_defaults_to_project_store_in_mixed_store_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    project_has_data: bool,
    repo_has_data: bool,
) -> None:
    project_root = tmp_path / "project-data"
    repo_root = tmp_path / "repo"
    project_beads_root = project_root / ".beads"
    repo_beads_root = repo_root / ".beads"
    project_beads_root.mkdir(parents=True)
    repo_beads_root.mkdir(parents=True)
    if project_has_data:
        (project_beads_root / "issues.db").write_text("project\n")
    if repo_has_data:
        (repo_beads_root / "issues.db").write_text("repo\n")

    _patch_project_resolution(
        monkeypatch,
        project_root=project_root,
        repo_root=repo_root,
        project_beads_root=project_beads_root,
    )
    monkeypatch.setenv("BEADS_DIR", str(repo_beads_root))

    context = beads_context.resolve_skill_beads_context(beads_dir=None)

    assert context.project_beads_root == project_beads_root
    assert context.beads_root == project_beads_root
    assert context.repo_root == repo_root
    assert context.override_warning is None


def test_resolve_skill_beads_context_warns_for_explicit_non_project_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project-data"
    repo_root = tmp_path / "repo"
    project_beads_root = project_root / ".beads"
    override_beads_root = repo_root / ".beads"
    project_beads_root.mkdir(parents=True)
    override_beads_root.mkdir(parents=True)

    _patch_project_resolution(
        monkeypatch,
        project_root=project_root,
        repo_root=repo_root,
        project_beads_root=project_beads_root,
    )

    context = beads_context.resolve_skill_beads_context(beads_dir=str(override_beads_root))

    assert context.beads_root == override_beads_root
    assert context.project_beads_root == project_beads_root
    assert context.override_warning is not None
    assert str(project_beads_root) in context.override_warning
    assert str(override_beads_root) in context.override_warning


def test_resolve_skill_beads_context_uses_explicit_override_when_project_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    override_beads_root = repo_root / ".beads"
    override_beads_root.mkdir(parents=True)

    monkeypatch.setattr(
        beads_context,
        "_resolve_project_context",
        lambda *, repo_dir: (_ for _ in ()).throw(RuntimeError("broken project config")),
    )

    context = beads_context.resolve_skill_beads_context(
        beads_dir=str(override_beads_root),
        repo_dir=str(repo_root),
    )

    assert context.beads_root == override_beads_root
    assert context.project_beads_root == override_beads_root
    assert context.repo_root == repo_root.resolve()
    assert context.override_warning is not None
    assert "project-scoped Beads resolution failed" in context.override_warning
    assert str(override_beads_root) in context.override_warning
    assert "RuntimeError: broken project config" in context.override_warning


def test_resolve_skill_beads_context_raises_without_explicit_override_when_project_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        beads_context,
        "_resolve_project_context",
        lambda *, repo_dir: (_ for _ in ()).throw(RuntimeError("broken project config")),
    )

    with pytest.raises(RuntimeError, match="broken project config"):
        beads_context.resolve_skill_beads_context(beads_dir=None)


@pytest.mark.parametrize("repo_input_kind", ["canonical", "linked-worktree"])
def test_resolve_skill_beads_context_uses_same_project_for_canonical_and_linked_repo_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo_input_kind: str,
) -> None:
    project_root_base = tmp_path / "atelier-data" / "projects"
    monkeypatch.setattr(paths, "projects_root", lambda: project_root_base)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.email", "test@example.com")
    _run_git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo_root, "add", "README.md")
    _run_git(repo_root, "commit", "-m", "seed")

    linked_worktree = tmp_path / "agent-worktree"
    _run_git(repo_root, "worktree", "add", "-b", "feature-worktree", str(linked_worktree), "HEAD")

    enlistment_path = str(repo_root.resolve())
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin=None)
    project_root.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "project": {
            "enlistment": enlistment_path,
            "origin": None,
            "repo_url": None,
        }
    }
    paths.project_config_sys_path(project_root).write_text(
        json.dumps(config_payload),
        encoding="utf-8",
    )
    expected_beads_root = project_root / ".beads"
    expected_beads_root.mkdir(parents=True, exist_ok=True)

    repo_dir = repo_root if repo_input_kind == "canonical" else linked_worktree
    context = beads_context.resolve_skill_beads_context(
        beads_dir=None,
        repo_dir=str(repo_dir),
    )

    assert context.project_beads_root == expected_beads_root
    assert context.beads_root == expected_beads_root
    assert context.override_warning is None
    assert context.repo_root == repo_dir.resolve()


def test_resolve_runtime_repo_dir_hint_prefers_agent_home_worktree(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    agent_home = tmp_path / "agent-home"
    agent_home.mkdir(parents=True)
    (agent_home / "worktree").symlink_to(repo_root)

    hint, warning = beads_context.resolve_runtime_repo_dir_hint(
        repo_dir=None,
        cwd=agent_home,
        env={},
    )

    assert hint == str(repo_root.resolve())
    assert warning is None


def test_resolve_runtime_repo_dir_hint_returns_explicit_worktree_repo_dir_without_warning() -> None:
    hint, warning = beads_context.resolve_runtime_repo_dir_hint(
        repo_dir="./worktree",
        cwd=Path("/tmp"),
        env={},
    )

    assert hint == "./worktree"
    assert warning is None


def test_resolve_runtime_repo_dir_hint_warns_on_legacy_atelier_project_fallback() -> None:
    hint, warning = beads_context.resolve_runtime_repo_dir_hint(
        repo_dir=None,
        cwd=Path("/tmp"),
        env={"ATELIER_PROJECT": "/repo/from-env"},
    )

    assert hint == "/repo/from-env"
    assert warning is not None
    assert "ATELIER_PROJECT" in warning
    assert "2026-07-01" in warning


def test_resolve_runtime_repo_dir_hint_warns_on_legacy_workspace_dir_fallback() -> None:
    hint, warning = beads_context.resolve_runtime_repo_dir_hint(
        repo_dir=None,
        cwd=Path("/tmp"),
        env={"ATELIER_WORKSPACE_DIR": "/repo/from-workspace-dir"},
    )

    assert hint == "/repo/from-workspace-dir"
    assert warning is not None
    assert "ATELIER_WORKSPACE_DIR" in warning
    assert "2026-07-01" in warning
