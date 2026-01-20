import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from typer.testing import CliRunner  # noqa: E402

import atelier.cli as cli  # noqa: E402
import atelier.commands.clean as clean_cmd  # noqa: E402
import atelier.commands.init as init_cmd  # noqa: E402
import atelier.commands.list as list_cmd  # noqa: E402
import atelier.commands.open as open_cmd  # noqa: E402
import atelier.editor as editor  # noqa: E402
import atelier.git as git  # noqa: E402
import atelier.paths as paths  # noqa: E402
import atelier.sessions as sessions_mod  # noqa: E402
import atelier.workspace as workspace  # noqa: E402

RAW_ORIGIN = "git@github.com:org/repo.git"
NORMALIZED_ORIGIN = git.normalize_origin_url(RAW_ORIGIN)


def enlistment_path_for(path: Path) -> str:
    return str(path.resolve())


def workspace_id_for(enlistment_path: str, branch: str) -> str:
    return workspace.workspace_identifier(enlistment_path, branch)


def make_init_args(**overrides: object) -> SimpleNamespace:
    data = {
        "branch_prefix": None,
        "branch_pr": None,
        "branch_history": None,
        "agent": None,
        "editor": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class DummyResult:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def write_project_config(project_dir: Path, enlistment_path: str) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "project": {
            "enlistment": enlistment_path,
            "origin": NORMALIZED_ORIGIN,
            "repo_url": RAW_ORIGIN,
        },
        "branch": {
            "prefix": "scott/",
            "pr": True,
            "history": "manual",
        },
    }
    paths.project_config_path(project_dir).write_text(
        json.dumps(config), encoding="utf-8"
    )
    return config


def make_open_config(enlistment_path: str, **overrides: object) -> dict:
    config = {
        "project": {
            "enlistment": enlistment_path,
            "origin": NORMALIZED_ORIGIN,
            "repo_url": RAW_ORIGIN,
        },
        "branch": {
            "prefix": "scott/",
            "pr": True,
            "history": "manual",
        },
        "agent": {"default": "codex", "options": {"codex": []}},
        "editor": {"default": "true", "options": {"true": []}},
        "atelier": {
            "version": "0.2.0",
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    overrides = dict(overrides)
    project_override = overrides.pop("project", None)
    if isinstance(project_override, dict):
        config["project"] = {**config["project"], **project_override}
    config.update(overrides)
    return config


def write_open_config(root: Path, enlistment_path: str, **overrides: object) -> dict:
    config = make_open_config(enlistment_path, **overrides)
    root.mkdir(parents=True, exist_ok=True)
    paths.project_config_path(root).write_text(json.dumps(config), encoding="utf-8")
    return config


def init_local_repo(root: Path) -> Path:
    repo = root / "origin"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"], check=True
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "chore: initial"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", "scott/feat-demo"], check=True
    )
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "feature.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "feat: demo change"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "checkout", "main"], check=True)
    return repo


def init_local_repo_without_feature(root: Path) -> Path:
    repo = root / "origin"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"], check=True
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "chore: initial"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


def write_workspace_config(
    workspace_dir: Path, branch: str, enlistment_path: str
) -> None:
    payload = {
        "workspace": {
            "branch": branch,
            "branch_pr": True,
            "branch_history": "manual",
            "id": workspace_id_for(enlistment_path, branch),
        },
        "atelier": {"version": "0.2.0", "created_at": "2026-01-01T00:00:00Z"},
    }
    (workspace_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def make_fake_git(
    branches: dict[Path, str],
    statuses: dict[Path, str],
    remotes: dict[tuple[Path, str], str],
):
    normalized_branches = {path.resolve(): value for path, value in branches.items()}
    normalized_statuses = {path.resolve(): value for path, value in statuses.items()}
    normalized_remotes = {
        (path.resolve(), branch): value for (path, branch), value in remotes.items()
    }

    def fake_run(
        cmd: list[str],
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        cwd: Path | None = None,
    ) -> DummyResult:
        if cmd[0] != "git":
            return DummyResult(returncode=1, stdout="")
        if "-C" not in cmd:
            return DummyResult(returncode=1, stdout="")
        repo_dir = Path(cmd[cmd.index("-C") + 1]).resolve()
        if "rev-parse" in cmd:
            branch = normalized_branches.get(repo_dir, "")
            return DummyResult(returncode=0, stdout=f"{branch}\n")
        if "status" in cmd and "--porcelain" in cmd:
            status = normalized_statuses.get(repo_dir, "")
            return DummyResult(returncode=0, stdout=status)
        if "ls-remote" in cmd:
            branch = cmd[-1]
            output = normalized_remotes.get((repo_dir, branch), "")
            return DummyResult(returncode=0, stdout=output)
        return DummyResult(returncode=1, stdout="")

    return fake_run


class TestNormalizeOriginUrl(TestCase):
    def test_owner_name_with_host(self) -> None:
        self.assertEqual(
            git.normalize_origin_url("github.com/owner/repo"),
            "github.com/owner/repo",
        )

    def test_https_normalizes(self) -> None:
        value = "https://github.com/owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")

    def test_ssh_scp_style(self) -> None:
        value = "git@github.com:owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")

    def test_ssh_scheme(self) -> None:
        value = "ssh://git@github.com/owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")


class TestResolveEditorCommand(TestCase):
    def test_config_precedence(self) -> None:
        config = {
            "editor": {
                "default": "cursor",
                "options": {"cursor": ["-w"]},
            }
        }
        with patch.dict(os.environ, {"EDITOR": "nano -w"}):
            self.assertEqual(editor.resolve_editor_command(config), ["cursor", "-w"])

    def test_env_fallback(self) -> None:
        config = {"editor": {"options": {}}}
        with patch.dict(os.environ, {"EDITOR": "nano -w"}):
            self.assertEqual(editor.resolve_editor_command(config), ["nano", "-w"])

    def test_vi_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(editor.resolve_editor_command({}), ["vi"])


class TestInitProject(TestCase):
    def test_init_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.config.shutil.which", return_value="/usr/bin/cursor"
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                self.assertTrue(config_path.exists())
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["enlistment"], enlistment_path)
                self.assertEqual(config["project"]["origin"], NORMALIZED_ORIGIN)
                self.assertEqual(config["project"]["repo_url"], RAW_ORIGIN)
                self.assertTrue(config["branch"]["pr"])
                self.assertEqual(config["branch"]["history"], "manual")
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertTrue((project_dir / "AGENTS.md").exists())
                self.assertTrue((project_dir / "templates" / "AGENTS.md").exists())
                self.assertTrue((project_dir / "PROJECT.md").exists())
                self.assertTrue((project_dir / "workspaces").is_dir())
            finally:
                os.chdir(original_cwd)

    def test_init_prefers_cursor_over_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.config.shutil.which", return_value="/usr/bin/cursor"
                    ),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "cursor")
            finally:
                os.chdir(original_cwd)

    def test_init_parses_editor_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "cursor -w"])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertEqual(config["editor"]["options"]["cursor"], ["-w"])
            finally:
                os.chdir(original_cwd)

    def test_init_uses_editor_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.config.shutil.which", return_value=None),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "nano")
                self.assertEqual(config["editor"]["options"]["nano"], ["-w"])
            finally:
                os.chdir(original_cwd)

    def test_init_with_flags_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                config = {
                    "project": {
                        "enlistment": enlistment_path,
                        "origin": git.normalize_origin_url(
                            "git@github.com:old/repo.git"
                        ),
                        "repo_url": "git@github.com:old/repo.git",
                    },
                    "branch": {
                        "prefix": "old/",
                        "pr": False,
                        "history": "merge",
                    },
                    "agent": {"default": "codex", "options": {"codex": ["--old"]}},
                    "editor": {"default": "nano", "options": {"nano": ["-w"]}},
                    "atelier": {
                        "id": "01OLD",
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                }
                with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )
                project_dir.mkdir(parents=True, exist_ok=True)
                paths.project_config_path(project_dir).write_text(
                    json.dumps(config), encoding="utf-8"
                )

                args = make_init_args(
                    branch_prefix="feat/",
                    branch_pr="false",
                    branch_history="merge",
                    agent="codex",
                    editor="cursor -w",
                )

                with (
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompt should not be called"),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)

                config_path = paths.project_config_path(project_dir)
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["enlistment"], enlistment_path)
                self.assertEqual(config["project"]["origin"], NORMALIZED_ORIGIN)
                self.assertEqual(config["project"]["repo_url"], RAW_ORIGIN)
                self.assertEqual(config["branch"]["prefix"], "feat/")
                self.assertFalse(config["branch"]["pr"])
                self.assertEqual(config["branch"]["history"], "merge")
                self.assertEqual(config["agent"]["default"], "codex")
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertEqual(config["editor"]["options"]["cursor"], ["-w"])
                self.assertTrue((project_dir / "workspaces").is_dir())
            finally:
                os.chdir(original_cwd)

    def test_init_creates_workspace_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                template_path = project_dir / "templates" / "WORKSPACE.md"
                self.assertTrue(template_path.exists())
                content = template_path.read_text(encoding="utf-8")
                self.assertIn("WORKSPACE.md", content)
            finally:
                os.chdir(original_cwd)


class TestListWorkspaces(TestCase):
    def test_list_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)

            alpha_branch = "scott/alpha"
            beta_branch = "scott/beta"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            beta_dir = paths.workspace_dir_for_branch(
                project_dir,
                beta_branch,
                workspace_id_for(enlistment_path, beta_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            repo_beta = beta_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha", repo_beta: "main"},
                statuses={repo_alpha: "", repo_beta: " M file.txt\n"},
                remotes={
                    (repo_alpha, "scott/alpha"): "deadbeef\trefs/heads/scott/alpha\n",
                    (repo_beta, "scott/beta"): "",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    list_cmd.list_workspaces(SimpleNamespace(status=True))
                lines = [
                    line.strip() for line in buffer.getvalue().splitlines() if line
                ]
                data = {
                    line.split()[0]: line.split()
                    for line in lines
                    if line.split()[0] in {alpha_branch, beta_branch}
                }
                self.assertEqual(data[alpha_branch][1:], ["yes", "yes", "yes"])
                self.assertEqual(data[beta_branch][1:], ["no", "unknown", "no"])
            finally:
                os.chdir(original_cwd)

    def test_list_default_only_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            beta_branch = "scott/beta"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            beta_dir = paths.workspace_dir_for_branch(
                project_dir,
                beta_branch,
                workspace_id_for(enlistment_path, beta_branch),
            )
            alpha_dir.mkdir(parents=True)
            beta_dir.mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    list_cmd.list_workspaces(SimpleNamespace())
                lines = [
                    line.strip() for line in buffer.getvalue().splitlines() if line
                ]
                self.assertEqual(lines, [alpha_branch, beta_branch])
            finally:
                os.chdir(original_cwd)


class TestCleanWorkspaces(TestCase):
    def test_clean_default_deletes_complete_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            complete_branch = "scott/complete"
            incomplete_branch = "scott/incomplete"
            complete_dir = paths.workspace_dir_for_branch(
                project_dir,
                complete_branch,
                workspace_id_for(enlistment_path, complete_branch),
            )
            incomplete_dir = paths.workspace_dir_for_branch(
                project_dir,
                incomplete_branch,
                workspace_id_for(enlistment_path, incomplete_branch),
            )
            (complete_dir / "repo").mkdir(parents=True)
            (incomplete_dir / "repo").mkdir(parents=True)
            write_workspace_config(complete_dir, complete_branch, enlistment_path)
            write_workspace_config(incomplete_dir, incomplete_branch, enlistment_path)

            repo_complete = complete_dir / "repo"
            repo_incomplete = incomplete_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_complete: "scott/complete", repo_incomplete: "main"},
                statuses={repo_complete: "", repo_incomplete: " M file.txt\n"},
                remotes={
                    (
                        repo_complete,
                        "scott/complete",
                    ): "abc\trefs/heads/scott/complete\n",
                    (repo_incomplete, "scott/incomplete"): "",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["y"])
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(complete_dir.exists())
                self.assertTrue(incomplete_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_all_flag_deletes_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            beta_branch = "scott/beta"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            beta_dir = paths.workspace_dir_for_branch(
                project_dir,
                beta_branch,
                workspace_id_for(enlistment_path, beta_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            repo_beta = beta_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha", repo_beta: "main"},
                statuses={repo_alpha: " M file.txt\n", repo_beta: ""},
                remotes={
                    (repo_alpha, "scott/alpha"): "",
                    (repo_beta, "scott/beta"): "abc\trefs/heads/scott/beta\n",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["y", "y"])
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
                self.assertFalse(beta_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_force_skips_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompted unexpectedly"),
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_positional_targets_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            beta_branch = "scott/beta"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            beta_dir = paths.workspace_dir_for_branch(
                project_dir,
                beta_branch,
                workspace_id_for(enlistment_path, beta_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            repo_beta = beta_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha", repo_beta: "scott/beta"},
                statuses={repo_alpha: "", repo_beta: ""},
                remotes={
                    (repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n",
                    (repo_beta, "scott/beta"): "abc\trefs/heads/scott/beta\n",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=True,
                            no_branch=False,
                            workspace_names=[beta_branch, "missing"],
                        )
                    )
                self.assertTrue(alpha_dir.exists())
                self.assertFalse(beta_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_skips_branch_deletion_with_no_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "atelier.commands.clean.delete_workspace_branch",
                        side_effect=AssertionError("deleted branch unexpectedly"),
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=True,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_deletes_branch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )
            deleted: list[tuple[str, str]] = []

            def fake_delete(repo_dir: Path, branch: str, default_branch: str) -> None:
                deleted.append((repo_dir.name, branch))

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "atelier.commands.clean.delete_workspace_branch", fake_delete
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertEqual(deleted, [("repo", "scott/alpha")])
            finally:
                os.chdir(original_cwd)


class TestCleanFlags(TestCase):
    def test_clean_short_flags(self) -> None:
        captured: dict[str, object] = {}

        def fake_clean(args: SimpleNamespace) -> None:
            captured["all"] = args.all
            captured["force"] = args.force

        runner = CliRunner()
        with patch("atelier.commands.clean.clean_workspaces", fake_clean):
            result = runner.invoke(cli.app, ["clean", "-A", "-F"])

        self.assertEqual(result.exit_code, 0)

        self.assertTrue(captured["all"])
        self.assertTrue(captured["force"])


class TestFindCodexSession(TestCase):
    def test_returns_most_recent_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            older = sessions / "session-old.json"
            newer = sessions / "session-new.json"

            older.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )
            newer.write_text(
                json.dumps({"messages": [{"role": "user", "content": target}]}),
                encoding="utf-8",
            )

            now = time.time()
            os.utime(older, (now - 100, now - 100))
            os.utime(newer, (now, now))

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            self.assertEqual(session, "session-new")

    def test_returns_session_id_from_jsonl_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".codex" / "sessions" / "2026" / "01" / "14"
            sessions.mkdir(parents=True)

            target = "atelier:01TEST:feat-demo"
            session_id = "019bbe1b-1c3c-7ef0-b7e6-61477c74ceb1"
            session_file = sessions / f"rollout-2026-01-14T12-03-26-{session_id}.jsonl"

            session_file.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "instructions": target,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            self.assertEqual(session, session_id)


class TestOpenWorkspace(TestCase):
    def test_open_creates_workspace_and_launches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                self.assertTrue((workspace_dir / "AGENTS.md").exists())
                self.assertTrue((workspace_dir / "PERSIST.md").exists())
                self.assertTrue((workspace_dir / "WORKSPACE.md").exists())
                self.assertTrue((workspace_dir / "config.json").exists())

                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )

                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Atelier Agent Contract", agents_content)
                self.assertIn("WORKSPACE.md", agents_content)
                self.assertIn("PERSIST.md", agents_content)

                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("## Integration Strategy", persist_content)
                self.assertIn("Pull requests expected: yes", persist_content)
                self.assertIn("History policy: manual", persist_content)

                self.assertTrue(any(cmd[:2] == ["git", "clone"] for cmd in commands))
                repo_path = (workspace_dir / "repo").resolve()
                self.assertTrue(
                    any(
                        cmd[0] == "git"
                        and any(
                            Path(part).resolve() == repo_path
                            for part in cmd
                            if isinstance(part, str) and part.startswith("/")
                        )
                        for cmd in commands
                    )
                )
                self.assertTrue(
                    any(cmd[0] == "codex" and "--cd" in cmd for cmd in commands)
                )
            finally:
                os.chdir(original_cwd)

    def test_open_with_prefixed_branch_does_not_double_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="scott/feat-demo")
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )
                self.assertFalse(
                    paths.workspace_dir_for_branch(
                        project_dir,
                        "scott/scott/feat-demo",
                        workspace_id_for(enlistment_path, "scott/scott/feat-demo"),
                    ).exists()
                )
                self.assertTrue(any(cmd[:2] == ["git", "clone"] for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_without_name_uses_current_branch_when_clean_and_pushed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_current_branch(repo_dir: Path) -> str | None:
                    if repo_dir == root:
                        return "feature/demo"
                    return "main"

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", fake_current_branch),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.git.git_branch_fully_pushed", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name=None))

                workspace_branch = "feature/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )
                self.assertTrue(any(cmd[0] == "codex" for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_edits_agents_after_clone_when_repo_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                editor_index = next(
                    index for index, cmd in enumerate(commands) if cmd[:1] == ["true"]
                )
                clone_index = next(
                    index
                    for index, cmd in enumerate(commands)
                    if cmd[:2] == ["git", "clone"]
                )
                self.assertLess(clone_index, editor_index)
            finally:
                os.chdir(original_cwd)

    def test_open_editor_uses_workspace_relative_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data dir"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                cwds: list[Path | None] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)
                    cwds.append(cwd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                editor_index = next(
                    index for index, cmd in enumerate(commands) if cmd[:1] == ["true"]
                )
                self.assertEqual(commands[editor_index][-1], "WORKSPACE.md")
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    "scott/feat-demo",
                    workspace_id_for(enlistment_path, "scott/feat-demo"),
                )
                self.assertEqual(cwds[editor_index], workspace_dir)
            finally:
                os.chdir(original_cwd)

    def test_open_skips_editor_when_repo_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertFalse(any(cmd[:1] == ["true"] for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_skips_editor_when_workspace_md_missing_for_existing_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_origin(NORMALIZED_ORIGIN)
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertFalse((workspace_dir / "WORKSPACE.md").exists())
                self.assertFalse((project_dir / "templates").exists())
                self.assertFalse(any(cmd[:1] == ["true"] for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_skips_default_checkout_with_dirty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "config",
                    "user.email",
                    "test@example.com",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "config", "user.name", "Test User"],
                check=True,
            )
            (repo_dir / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo_dir), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo_dir), "commit", "-m", "chore: init"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "branch", "-M", "main"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "checkout", "-b", "scott/feat-demo"],
                check=True,
            )
            (repo_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertFalse(
                    any(
                        cmd == ["git", "-C", str(repo_dir), "checkout", "main"]
                        for cmd in commands
                    )
                )
            finally:
                os.chdir(original_cwd)

    def test_open_does_not_modify_existing_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            payload = {
                "workspace": {
                    "branch": workspace_branch,
                    "branch_pr": False,
                    "branch_history": "squash",
                    "id": workspace_id_for(enlistment_path, workspace_branch),
                },
                "atelier": {"version": "0.2.0", "created_at": "2026-01-01T00:00:00Z"},
            }
            (workspace_dir / "config.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            agents_path = workspace_dir / "AGENTS.md"
            workspace_path = workspace_dir / "WORKSPACE.md"
            agents_path.write_text("agents stub\n", encoding="utf-8")
            workspace_path.write_text("workspace stub\n", encoding="utf-8")
            os.utime(agents_path, (1_000_000_000, 1_000_000_000))
            os.utime(workspace_path, (1_000_000_000, 1_000_000_000))
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir()

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(stdout=RAW_ORIGIN),
                    ),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertEqual(
                    agents_path.read_text(encoding="utf-8"), "agents stub\n"
                )
                self.assertEqual(
                    workspace_path.read_text(encoding="utf-8"), "workspace stub\n"
                )
                self.assertEqual(int(agents_path.stat().st_mtime), 1_000_000_000)
                self.assertEqual(int(workspace_path.stat().st_mtime), 1_000_000_000)
                self.assertFalse((workspace_dir / "PERSIST.md").exists())
                self.assertFalse((workspace_dir / "BACKGROUND.md").exists())
            finally:
                os.chdir(original_cwd)

    def test_open_errors_when_repo_is_not_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            (workspace_dir / "repo").mkdir(parents=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with self.assertRaises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_when_origin_remote_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with self.assertRaises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_accepts_raw_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    workspace_branch = "feature/demo-branch"
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name=workspace_branch, raw=True)
                    )

                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                self.assertTrue((workspace_dir / "AGENTS.md").exists())
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )
            finally:
                os.chdir(original_cwd)

    def test_open_copies_workspace_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            config = {
                "project": {
                    "enlistment": enlistment_path,
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                },
                "branch": {"prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "atelier": {
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            paths.project_config_path(project_dir).write_text(
                json.dumps(config), encoding="utf-8"
            )
            templates_dir = project_dir / "templates"
            templates_dir.mkdir()
            template_content = "<!-- workspace template -->\n"
            (templates_dir / "WORKSPACE.md").write_text(
                template_content, encoding="utf-8"
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_template = workspace_dir / "WORKSPACE.md"
                self.assertTrue(workspace_template.exists())
                self.assertEqual(
                    workspace_template.read_text(encoding="utf-8"), template_content
                )
            finally:
                os.chdir(original_cwd)

    def test_open_normalizes_workspace_name_and_preserves_branch_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat/demo"))

                workspace_branch = "scott/feat/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )
            finally:
                os.chdir(original_cwd)

    def test_open_renders_direct_integration_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                branch={
                    "prefix": "scott/",
                    "pr": False,
                    "history": "squash",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Pull requests expected: no", persist_content)
                self.assertIn("History policy: squash", persist_content)
                self.assertIn("collapsed into a single commit", persist_content)
            finally:
                os.chdir(original_cwd)

    def test_open_overrides_branch_settings_for_new_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            branch_pr="false",
                            branch_history="merge",
                        )
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertFalse(workspace_config["workspace"]["branch_pr"])
                self.assertEqual(
                    workspace_config["workspace"]["branch_history"], "merge"
                )

                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Pull requests expected: no", persist_content)
                self.assertIn("History policy: merge", persist_content)
            finally:
                os.chdir(original_cwd)

    def test_open_uses_remote_branch_and_writes_background_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            origin_repo = init_local_repo(root)
            origin_raw = str(origin_repo)
            origin_norm = git.normalize_origin_url(origin_raw)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, origin_norm
                )
            write_open_config(
                project_dir,
                enlistment_path,
                project={"origin": origin_norm, "repo_url": origin_raw},
            )
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)
                    if cmd[0] == "codex":
                        return
                    if cmd[0] == "true":
                        background_content = (
                            workspace_dir / "BACKGROUND.md"
                        ).read_text(encoding="utf-8")
                        self.assertIn(
                            "Commit Subjects since merge-base", background_content
                        )
                    subprocess.run(cmd, cwd=cwd, check=True)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=origin_raw),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertTrue((workspace_dir / "BACKGROUND.md").exists())
                background_content = (workspace_dir / "BACKGROUND.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Commit Subjects since merge-base", background_content)
                self.assertIn("feat: demo change", background_content)

                head = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(workspace_dir / "repo"),
                        "rev-parse",
                        "--abbrev-ref",
                        "HEAD",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(head.stdout.strip(), "scott/feat-demo")
                self.assertTrue(any(cmd[0] == "codex" for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_skips_background_for_new_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            origin_repo = init_local_repo_without_feature(root)
            origin_raw = str(origin_repo)
            origin_norm = git.normalize_origin_url(origin_raw)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, origin_norm
                )
            write_open_config(
                project_dir,
                enlistment_path,
                project={"origin": origin_norm, "repo_url": origin_raw},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)
                    if cmd[0] == "codex":
                        return
                    subprocess.run(cmd, cwd=cwd, check=True)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=origin_raw),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                self.assertFalse((workspace_dir / "BACKGROUND.md").exists())
            finally:
                os.chdir(original_cwd)

    def test_open_uses_raw_branch_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                class DummyResult:
                    def __init__(self, returncode: int = 1, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    workspace_branch = "feature/demo-branch"
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            raw=True,
                        )
                    )

                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = json.loads(
                    (workspace_dir / "config.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], workspace_branch
                )
                self.assertTrue(
                    any(
                        len(cmd) >= 6
                        and cmd[0] == "git"
                        and cmd[1] == "-C"
                        and cmd[3:6] == ["checkout", "-b", workspace_branch]
                        for cmd in commands
                    )
                )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_on_branch_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, "scott/mismatch", enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with self.assertRaises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_on_branch_settings_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with self.assertRaises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(
                                workspace_name="feat-demo",
                                branch_pr="false",
                                branch_history="manual",
                            )
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_rejects_invalid_branch_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                branch={"prefix": "scott/", "history": "sideways"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with self.assertRaises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)
