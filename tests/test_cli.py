import json
import os
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
                args = SimpleNamespace(repo_url="owner/repo")
                responses = iter(["", "", "", "", "", ""])

                with patch("builtins.input", lambda _: next(responses)):
                    cli.init_project(args)

                config_path = root / ".atelier.json"
                self.assertTrue(config_path.exists())
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["project"]["name"], root.name)
                self.assertEqual(
                    config["project"]["repo_url"], "git@github.com:owner/repo.git"
                )
                self.assertEqual(config["branch"]["default"], "main")
                self.assertEqual(config["editor"]["default"], "vi")
                self.assertTrue((root / "AGENTS.md").exists())
                self.assertTrue((root / "workspaces").is_dir())
            finally:
                os.chdir(original_cwd)


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
                "atelier": {"id": "01TEST", "version": "0.2.0", "created_at": "2026-01-01T00:00:00Z"},
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

                with patch("atelier.cli.run_command", fake_run), patch(
                    "atelier.cli.find_codex_session", return_value=None
                ), patch("atelier.cli.subprocess.run", return_value=DummyResult()):
                    cli.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_dir = root / "workspaces" / "feat-demo"
                self.assertTrue((workspace_dir / "AGENTS.md").exists())
                self.assertTrue((workspace_dir / ".atelier.workspace.json").exists())

                workspace_config = json.loads(
                    (workspace_dir / ".atelier.workspace.json").read_text(encoding="utf-8")
                )
                self.assertEqual(workspace_config["workspace"]["branch"], "scott/feat-demo")

                agents_content = (workspace_dir / "AGENTS.md").read_text(encoding="utf-8")
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
                self.assertTrue(any(cmd[0] == "codex" and "--cd" in cmd for cmd in commands))
            finally:
                os.chdir(original_cwd)
