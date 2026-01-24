import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.snapshot as snapshot_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    enlistment_path_for,
    workspace_id_for,
    write_open_config,
    write_workspace_config,
)


class TestSnapshotCommand:
    def test_snapshot_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(
                workspace_dir,
                workspace_branch,
                enlistment_path,
                session={
                    "agent": "codex",
                    "id": "sess-123",
                    "resume_command": "codex --resume sess-123",
                },
            )

            (workspace_dir / "SUCCESS.md").write_text(
                "success content\n", encoding="utf-8"
            )
            (workspace_dir / "PERSIST.md").write_text(
                "persist content\n", encoding="utf-8"
            )
            (workspace_dir / "BACKGROUND.md").write_text(
                "background content\n", encoding="utf-8"
            )

            def fake_commits_ahead(
                _repo_dir: Path, base: str, branch: str, *, git_path: str | None = None
            ) -> int:
                if base == "main" and branch == workspace_branch:
                    return 2
                if base == workspace_branch and branch == "main":
                    return 1
                return 0

            buffer = io.StringIO()
            with (
                patch(
                    "atelier.commands.snapshot.git.resolve_repo_enlistment",
                    return_value=(root, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch(
                    "atelier.commands.snapshot.git.git_is_repo",
                    return_value=True,
                ),
                patch(
                    "atelier.commands.snapshot.git.git_current_branch",
                    return_value=workspace_branch,
                ),
                patch(
                    "atelier.commands.snapshot.git.git_is_clean",
                    return_value=False,
                ),
                patch(
                    "atelier.commands.snapshot.git.git_status_porcelain",
                    return_value=[" M file.txt", "?? new.txt"],
                ),
                patch(
                    "atelier.commands.snapshot.git.git_default_branch",
                    return_value="main",
                ),
                patch(
                    "atelier.commands.snapshot.git.git_commits_ahead",
                    side_effect=fake_commits_ahead,
                ),
                patch(
                    "atelier.commands.snapshot.git.git_diff_name_status",
                    return_value=["M file.txt", "A new.txt"],
                ),
                patch(
                    "atelier.commands.snapshot.git.git_diff_stat",
                    return_value=[
                        " file.txt | 2 +-",
                        " new.txt | 1 +",
                        " 2 files changed, 2 insertions(+), 1 deletion(-)",
                    ],
                ),
                patch(
                    "atelier.commands.snapshot.git.git_ls_files",
                    return_value=["README.md", "file.txt", "new.txt"],
                ),
                patch(
                    "atelier.commands.snapshot.sessions.find_codex_session",
                    return_value="sess-abc",
                ),
                patch("sys.stdout", buffer),
            ):
                snapshot_cmd.snapshot_workspace(SimpleNamespace(workspace_name="alpha"))

            snapshot_path = workspace_dir / "SNAPSHOT.md"
            assert snapshot_path.exists()
            content = snapshot_path.read_text(encoding="utf-8")
            assert "# Workspace Snapshot" in content
            assert "SUCCESS.md" in content
            assert "success content" in content
            assert "PERSIST.md" in content
            assert "persist content" in content
            assert "BACKGROUND.md" in content
            assert "background content" in content
            assert "Git Status" in content
            assert "M file.txt" in content
            assert "?? new.txt" in content
            assert "Mainline Comparison" in content
            assert "Commits ahead: 2" in content
            assert "Commits behind: 1" in content
            assert "Diffstat" in content
            assert "file.txt | 2 +-" in content
            assert "File List (tracked)" in content
            assert "README.md" in content
            assert "Agent Session (Best-effort)" in content
            assert "Stored session id: `sess-123`" in content
            assert "Discoverable Codex session id: `sess-abc`" in content
            assert "Wrote snapshot to" in buffer.getvalue()
