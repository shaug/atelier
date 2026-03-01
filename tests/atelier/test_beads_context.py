from __future__ import annotations

from pathlib import Path

import pytest

from atelier import beads_context


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
