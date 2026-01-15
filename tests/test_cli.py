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

import atelier.cli as cli  # noqa: E402


def make_init_args(**overrides: object) -> SimpleNamespace:
    data = {
        "project_name": None,
        "project_name_flag": None,
        "repo_url": None,
        "branch_default": None,
        "branch_prefix": None,
        "agent": None,
        "editor": None,
        "workspaces_root": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class DummyResult:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def write_project_config(root: Path) -> dict:
    config = {
        "project": {"name": "demo", "repo_url": "git@github.com:org/repo.git"},
        "branch": {"default": "main", "prefix": "scott/"},
        "workspaces": {"root": "workspaces"},
    }
    (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")
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


def write_workspace_config(workspace_dir: Path, name: str, branch: str) -> None:
    payload = {
        "workspace": {
            "name": name,
            "branch": branch,
            "id": f"atelier:01TEST:{name}",
        },
        "atelier": {"version": "0.2.0", "created_at": "2026-01-01T00:00:00Z"},
    }
    (workspace_dir / ".atelier.workspace.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


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


class TestUlid(TestCase):
    def test_ulid_format(self) -> None:
        value = cli.ulid_now()
        self.assertEqual(len(value), 26)
        for ch in value:
            self.assertIn(ch, cli.ULID_ALPHABET)


class TestNormalizeRepoUrl(TestCase):
    def test_owner_name(self) -> None:
        self.assertEqual(
            cli.normalize_repo_url("owner/repo"),
            "git@github.com:owner/repo.git",
        )

    def test_github_prefix(self) -> None:
        self.assertEqual(
            cli.normalize_repo_url("github.com/owner/repo"),
            "git@github.com:owner/repo.git",
        )

    def test_https_passthrough(self) -> None:
        value = "https://github.com/owner/repo.git"
        self.assertEqual(cli.normalize_repo_url(value), value)

    def test_ssh_passthrough(self) -> None:
        value = "git@github.com:owner/repo.git"
        self.assertEqual(cli.normalize_repo_url(value), value)


class TestResolveEditorCommand(TestCase):
    def test_config_precedence(self) -> None:
        config = {
            "editor": {
                "default": "cursor",
                "options": {"cursor": ["-w"]},
            }
        }
        with patch.dict(os.environ, {"EDITOR": "nano -w"}):
            self.assertEqual(cli.resolve_editor_command(config), ["cursor", "-w"])

    def test_env_fallback(self) -> None:
        config = {"editor": {"options": {}}}
        with patch.dict(os.environ, {"EDITOR": "nano -w"}):
            self.assertEqual(cli.resolve_editor_command(config), ["nano", "-w"])

    def test_vi_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli.resolve_editor_command({}), ["vi"])


class TestInitProject(TestCase):
    def test_init_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(repo_url="owner/repo")
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.cli.shutil.which", return_value="/usr/bin/cursor"),
                ):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                self.assertTrue(config_path.exists())
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["name"], root.name)
                self.assertEqual(
                    config["project"]["repo_url"], "git@github.com:owner/repo.git"
                )
                self.assertEqual(config["branch"]["default"], "main")
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertTrue((root / "AGENTS.md").exists())
                self.assertTrue((root / "workspaces").is_dir())
            finally:
                os.chdir(original_cwd)

    def test_init_prefers_cursor_over_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(repo_url="owner/repo")
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.cli.shutil.which", return_value="/usr/bin/cursor"),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                ):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "cursor")
            finally:
                os.chdir(original_cwd)

    def test_init_parses_editor_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(repo_url="owner/repo")
                responses = iter(["", "", "", "", "cursor -w", ""])

                with patch("builtins.input", lambda _: next(responses)):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertEqual(config["editor"]["options"]["cursor"], ["-w"])
            finally:
                os.chdir(original_cwd)

    def test_init_uses_editor_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(repo_url="owner/repo")
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.cli.shutil.which", return_value=None),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                ):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["editor"]["default"], "nano")
                self.assertEqual(config["editor"]["options"]["nano"], ["-w"])
            finally:
                os.chdir(original_cwd)

    def test_init_with_flags_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                config = {
                    "project": {
                        "name": "old",
                        "repo_url": "git@github.com:old/repo.git",
                    },
                    "branch": {"default": "main", "prefix": "old/"},
                    "agent": {"default": "codex", "options": {"codex": ["--old"]}},
                    "editor": {"default": "nano", "options": {"nano": ["-w"]}},
                    "workspaces": {"root": "old-workspaces"},
                    "atelier": {
                        "id": "01OLD",
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                }
                (root / ".atelier.json").write_text(
                    json.dumps(config), encoding="utf-8"
                )

                args = make_init_args(
                    project_name_flag="flag-project",
                    repo_url="org/new-repo",
                    branch_default="develop",
                    branch_prefix="feat/",
                    agent="codex",
                    editor="cursor -w",
                    workspaces_root="new-workspaces",
                )

                with patch(
                    "builtins.input",
                    side_effect=AssertionError("prompt should not be called"),
                ):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["name"], "flag-project")
                self.assertEqual(
                    config["project"]["repo_url"], "git@github.com:org/new-repo.git"
                )
                self.assertEqual(config["branch"]["default"], "develop")
                self.assertEqual(config["branch"]["prefix"], "feat/")
                self.assertEqual(config["agent"]["default"], "codex")
                self.assertEqual(config["editor"]["default"], "cursor")
                self.assertEqual(config["editor"]["options"]["cursor"], ["-w"])
                self.assertEqual(config["workspaces"]["root"], "new-workspaces")
                self.assertTrue((root / "new-workspaces").is_dir())
            finally:
                os.chdir(original_cwd)

    def test_init_uses_positional_project_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(
                    project_name="positional-project",
                    repo_url="owner/repo",
                )
                responses = iter(["", "", "", "", ""])

                with patch("builtins.input", lambda _: next(responses)):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["name"], "positional-project")
            finally:
                os.chdir(original_cwd)


class TestListWorkspaces(TestCase):
    def test_list_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project_config(root)

            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            beta_dir = workspaces_root / "beta"
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")
            write_workspace_config(beta_dir, "beta", "scott/beta")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch("sys.stdout", buffer),
                ):
                    cli.list_workspaces(SimpleNamespace(status=True))
                lines = [
                    line.strip() for line in buffer.getvalue().splitlines() if line
                ]
                data = {
                    line.split()[0]: line.split()
                    for line in lines
                    if line.split()[0] in {"alpha", "beta"}
                }
                self.assertEqual(data["alpha"][1:], ["yes", "yes", "yes"])
                self.assertEqual(data["beta"][1:], ["no", "unknown", "no"])
            finally:
                os.chdir(original_cwd)

    def test_list_default_only_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            beta_dir = workspaces_root / "beta"
            alpha_dir.mkdir(parents=True)
            beta_dir.mkdir(parents=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with patch("sys.stdout", buffer):
                    cli.list_workspaces(SimpleNamespace())
                lines = [
                    line.strip() for line in buffer.getvalue().splitlines() if line
                ]
                self.assertEqual(lines, ["alpha", "beta"])
            finally:
                os.chdir(original_cwd)


class TestCleanWorkspaces(TestCase):
    def test_clean_default_deletes_complete_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project_config(root)
            workspaces_root = root / "workspaces"
            complete_dir = workspaces_root / "complete"
            incomplete_dir = workspaces_root / "incomplete"
            (complete_dir / "repo").mkdir(parents=True)
            (incomplete_dir / "repo").mkdir(parents=True)
            write_workspace_config(complete_dir, "complete", "scott/complete")
            write_workspace_config(incomplete_dir, "incomplete", "scott/incomplete")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    cli.clean_workspaces(
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
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            beta_dir = workspaces_root / "beta"
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")
            write_workspace_config(beta_dir, "beta", "scott/beta")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    cli.clean_workspaces(
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
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompted unexpectedly"),
                    ),
                ):
                    cli.clean_workspaces(
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
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            beta_dir = workspaces_root / "beta"
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")
            write_workspace_config(beta_dir, "beta", "scott/beta")

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
                with patch("atelier.cli.subprocess.run", fake_run):
                    cli.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=True,
                            no_branch=False,
                            workspace_names=["workspaces/beta", "missing"],
                        )
                    )
                self.assertTrue(alpha_dir.exists())
                self.assertFalse(beta_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_skips_branch_deletion_with_no_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch(
                        "atelier.cli.delete_workspace_branch",
                        side_effect=AssertionError("deleted branch unexpectedly"),
                    ),
                ):
                    cli.clean_workspaces(
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
            write_project_config(root)
            workspaces_root = root / "workspaces"
            alpha_dir = workspaces_root / "alpha"
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, "alpha", "scott/alpha")

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
                    patch("atelier.cli.subprocess.run", fake_run),
                    patch("atelier.cli.delete_workspace_branch", fake_delete),
                ):
                    cli.clean_workspaces(
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

        with (
            patch.object(sys, "argv", ["atelier", "clean", "-A", "-F"]),
            patch("atelier.cli.clean_workspaces", fake_clean),
        ):
            cli.main()

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

            with patch("atelier.cli.Path.home", return_value=home):
                session = cli.find_codex_session("01TEST", "feat-demo")

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

            with patch("atelier.cli.Path.home", return_value=home):
                session = cli.find_codex_session("01TEST", "feat-demo")

            self.assertEqual(session, session_id)


class TestOpenWorkspace(TestCase):
    def test_open_creates_workspace_and_launches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "project": {"name": "demo", "repo_url": "git@github.com:org/repo.git"},
                "branch": {"default": "main", "prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")

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
                    patch("atelier.cli.run_command", fake_run),
                    patch("atelier.cli.find_codex_session", return_value=None),
                    patch("atelier.cli.subprocess.run", return_value=DummyResult()),
                ):
                    cli.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", branch=None)
                    )

                workspace_dir = root / "workspaces" / "feat-demo"
                self.assertTrue((workspace_dir / "AGENTS.md").exists())
                self.assertTrue((workspace_dir / ".atelier.workspace.json").exists())

                workspace_config = json.loads(
                    (workspace_dir / ".atelier.workspace.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], "scott/feat-demo"
                )

                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("atelier:01TEST:feat-demo", agents_content)

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

    def test_open_accepts_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "project": {"name": "demo", "repo_url": "git@github.com:org/repo.git"},
                "branch": {"default": "main", "prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")

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
                    patch("atelier.cli.run_command", fake_run),
                    patch("atelier.cli.find_codex_session", return_value=None),
                    patch("atelier.cli.subprocess.run", return_value=DummyResult()),
                ):
                    cli.open_workspace(
                        SimpleNamespace(workspace_name="workspaces/feat-demo")
                    )

                workspace_dir = root / "workspaces" / "feat-demo"
                self.assertTrue((workspace_dir / "AGENTS.md").exists())
                workspace_config = json.loads(
                    (workspace_dir / ".atelier.workspace.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(workspace_config["workspace"]["name"], "feat-demo")
            finally:
                os.chdir(original_cwd)

    def test_open_uses_remote_branch_and_appends_commit_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin_repo = init_local_repo(root)
            config = {
                "project": {"name": "demo", "repo_url": str(origin_repo)},
                "branch": {"default": "main", "prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")

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
                    patch("atelier.cli.run_command", fake_run),
                    patch("atelier.cli.find_codex_session", return_value=None),
                ):
                    cli.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", branch=None)
                    )

                workspace_dir = root / "workspaces" / "feat-demo"
                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Latest Commit Message(s)", agents_content)
                self.assertIn("feat: demo change", agents_content)
                self.assertIn("Review vs Mainline", agents_content)

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

    def test_open_skips_branch_summary_for_new_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin_repo = init_local_repo_without_feature(root)
            config = {
                "project": {"name": "demo", "repo_url": str(origin_repo)},
                "branch": {"default": "main", "prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")

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
                    patch("atelier.cli.run_command", fake_run),
                    patch("atelier.cli.find_codex_session", return_value=None),
                ):
                    cli.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", branch=None)
                    )

                workspace_dir = root / "workspaces" / "feat-demo"
                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("Latest Commit Message(s)", agents_content)
                self.assertNotIn("Review vs Mainline", agents_content)
            finally:
                os.chdir(original_cwd)

    def test_open_uses_explicit_branch_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "project": {"name": "demo", "repo_url": "git@github.com:org/repo.git"},
                "branch": {"default": "main", "prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "true", "options": {"true": []}},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")

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
                    patch("atelier.cli.run_command", fake_run),
                    patch("atelier.cli.find_codex_session", return_value=None),
                    patch("atelier.cli.subprocess.run", return_value=DummyResult()),
                ):
                    cli.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            branch="feature/demo-branch",
                        )
                    )

                workspace_dir = root / "workspaces" / "feat-demo"
                workspace_config = json.loads(
                    (workspace_dir / ".atelier.workspace.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    workspace_config["workspace"]["branch"], "feature/demo-branch"
                )
                self.assertTrue(
                    any(
                        len(cmd) >= 6
                        and cmd[0] == "git"
                        and cmd[1] == "-C"
                        and cmd[3:6] == ["checkout", "-b", "feature/demo-branch"]
                        for cmd in commands
                    )
                )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_on_branch_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "project": {"name": "demo", "repo_url": "git@github.com:org/repo.git"},
                "branch": {"default": "main", "prefix": "scott/"},
                "workspaces": {"root": "workspaces"},
                "atelier": {
                    "id": "01TEST",
                    "version": "0.2.0",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            }
            (root / ".atelier.json").write_text(json.dumps(config), encoding="utf-8")
            workspace_dir = root / "workspaces" / "feat-demo"
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, "feat-demo", "scott/feat-demo")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with self.assertRaises(SystemExit):
                    cli.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", branch="feat-demo")
                    )
            finally:
                os.chdir(original_cwd)
