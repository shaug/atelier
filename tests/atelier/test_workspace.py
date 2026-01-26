import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.git as git
import atelier.paths as paths
import atelier.workspace as workspace
from tests.atelier.helpers import (
    enlistment_path_for,
    init_local_repo,
    init_local_repo_without_feature,
    write_workspace_config,
)


def test_resolve_workspace_target_prefers_exact_workspace_before_prefix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        enlistment_path = enlistment_path_for(root)
        project_dir = root / "project"
        project_dir.mkdir()

        name = "team/feature"
        branch_prefix = "scott/"
        exact_branch = name
        prefixed_branch = f"{branch_prefix}{name}"

        exact_dir = paths.workspace_dir_for_branch(
            project_dir,
            exact_branch,
            workspace.workspace_identifier(enlistment_path, exact_branch),
        )
        prefixed_dir = paths.workspace_dir_for_branch(
            project_dir,
            prefixed_branch,
            workspace.workspace_identifier(enlistment_path, prefixed_branch),
        )
        exact_dir.mkdir(parents=True)
        prefixed_dir.mkdir(parents=True)
        write_workspace_config(exact_dir, exact_branch, enlistment_path)
        write_workspace_config(prefixed_dir, prefixed_branch, enlistment_path)

        with patch("atelier.workspace._branch_exists", return_value=False):
            branch, workspace_dir, exists = workspace.resolve_workspace_target(
                project_dir,
                enlistment_path,
                name,
                branch_prefix,
                False,
            )

        assert branch == exact_branch
        assert workspace_dir == exact_dir
        assert exists is True


def test_capture_workspace_base_records_default_branch_head() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = init_local_repo_without_feature(root)
        base = workspace.capture_workspace_base(str(repo))
        assert base is not None
        assert base.get("default_branch") == "main"
        assert base.get("sha") == git.git_rev_parse(repo, "main")
        assert base.get("captured_at")


def test_workspace_committed_work_counts_commits_since_base() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = init_local_repo(root)
        base_sha = git.git_rev_parse(repo, "main")
        assert base_sha is not None
        work_commits, committed_work = workspace.workspace_committed_work(
            repo, "scott/feat-demo", base_sha
        )
        assert work_commits == 1
        assert committed_work is True
