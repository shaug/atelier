import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.paths as paths


class TestNormalizedDirNames:
    def test_project_dir_name_normalizes_enlistment_path(self) -> None:
        enlistment = "/path/to/gumshoe"
        expected_base = "gumshoe"
        expected_hash = hashlib.sha256(enlistment.encode("utf-8")).hexdigest()[:8]
        assert paths.project_dir_name(enlistment) == f"{expected_base}-{expected_hash}"

    def test_workspace_dir_name_normalizes_branch(self) -> None:
        branch = " .feat/demo. "
        workspace_id = f"atelier:/repo:{branch}"
        expected_base = "feat-demo"
        expected_hash = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:8]
        assert paths.workspace_dir_name(branch, workspace_id) == (
            f"{expected_base}-{expected_hash}"
        )


class TestLegacyDirFallbacks:
    def test_project_dir_prefers_legacy_hash(self) -> None:
        origin = "github.com/org/repo"
        enlistment = "/repo"
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            legacy_dir = data_dir / paths.PROJECTS_DIRNAME / paths.project_key(origin)
            legacy_dir.mkdir(parents=True)
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                assert (
                    paths.project_dir_for_enlistment(enlistment, origin) == legacy_dir
                )

    def test_project_dir_uses_normalized_name_without_legacy(self) -> None:
        origin = "github.com/org/repo"
        enlistment = "/repo"
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                expected = (
                    data_dir
                    / paths.PROJECTS_DIRNAME
                    / paths.project_dir_name(enlistment)
                )
                assert paths.project_dir_for_enlistment(enlistment, origin) == expected

    def test_workspace_dir_prefers_legacy_hash(self) -> None:
        branch = "feat/demo"
        workspace_id = "atelier:/repo:feat/demo"
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            legacy_dir = (
                project_dir / paths.WORKSPACES_DIRNAME / paths.workspace_key(branch)
            )
            legacy_dir.mkdir(parents=True)
            assert (
                paths.workspace_dir_for_branch(project_dir, branch, workspace_id)
                == legacy_dir
            )

    def test_workspace_dir_uses_normalized_name_without_legacy(self) -> None:
        branch = "feat/demo"
        workspace_id = "atelier:/repo:feat/demo"
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            expected = (
                project_dir
                / paths.WORKSPACES_DIRNAME
                / paths.workspace_dir_name(branch, workspace_id)
            )
            assert (
                paths.workspace_dir_for_branch(project_dir, branch, workspace_id)
                == expected
            )


class TestBeadsPaths:
    def test_project_beads_dir_uses_beads_dirname(self) -> None:
        project_dir = Path("/tmp/project")
        assert paths.project_beads_dir(project_dir) == project_dir / paths.BEADS_DIRNAME


class TestDataDirPaths:
    def test_project_worktrees_dir_uses_worktrees_dirname(self) -> None:
        project_dir = Path("/tmp/project")
        assert (
            paths.project_worktrees_dir(project_dir)
            == project_dir / paths.WORKTREES_DIRNAME
        )

    def test_project_skills_dir_uses_skills_dirname(self) -> None:
        project_dir = Path("/tmp/project")
        assert (
            paths.project_skills_dir(project_dir)
            == project_dir / paths.SKILLS_DIRNAME
        )

    def test_project_agents_dir_uses_agents_dirname(self) -> None:
        project_dir = Path("/tmp/project")
        assert (
            paths.project_agents_dir(project_dir)
            == project_dir / paths.AGENTS_DIRNAME
        )
