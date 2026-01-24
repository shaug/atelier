import io
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from typer.testing import CliRunner  # noqa: E402

import atelier  # noqa: E402
import atelier.cli as cli  # noqa: E402
import atelier.commands.config as config_cmd  # noqa: E402
import atelier.commands.edit as edit_cmd  # noqa: E402
import atelier.commands.init as init_cmd  # noqa: E402
import atelier.commands.open as open_cmd  # noqa: E402
import atelier.commands.shell as shell_cmd  # noqa: E402
import atelier.commands.template as template_cmd  # noqa: E402
import atelier.commands.upgrade as upgrade_cmd  # noqa: E402
import atelier.commands.work as work_cmd  # noqa: E402
import atelier.config as config  # noqa: E402
import atelier.git as git  # noqa: E402
import atelier.paths as paths  # noqa: E402
import atelier.sessions as sessions_mod  # noqa: E402
import atelier.templates as templates  # noqa: E402
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
        "editor_edit": None,
        "editor_work": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class DummyResult:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


class BaseAtelierTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch(
            "atelier.agents.available_agent_names",
            return_value=("codex", "claude"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        io_patcher = patch("atelier.io._use_questionary", return_value=False)
        io_patcher.start()
        self.addCleanup(io_patcher.stop)
        input_patcher = patch(
            "builtins.input",
            side_effect=AssertionError("prompted unexpectedly"),
        )
        input_patcher.start()
        self.addCleanup(input_patcher.stop)


def write_project_config(project_dir: Path, enlistment_path: str) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = {
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
    parsed = config.ProjectConfig.model_validate(payload)
    config.write_project_config(paths.project_config_path(project_dir), parsed)
    return parsed.model_dump()


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
        "editor": {"edit": ["true"], "work": ["true"]},
        "atelier": {
            "version": atelier.__version__,
            "created_at": "2026-01-01T00:00:00Z",
            "upgrade": "ask",
        },
    }
    overrides = dict(overrides)
    project_override = overrides.pop("project", None)
    if isinstance(project_override, dict):
        config["project"] = {**config["project"], **project_override}
    config.update(overrides)
    return config


def write_open_config(root: Path, enlistment_path: str, **overrides: object) -> dict:
    config_payload = make_open_config(enlistment_path, **overrides)
    root.mkdir(parents=True, exist_ok=True)
    parsed = config.ProjectConfig.model_validate(config_payload)
    config.write_project_config(paths.project_config_path(root), parsed)
    return parsed.model_dump()


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
        "atelier": {
            "version": atelier.__version__,
            "created_at": "2026-01-01T00:00:00Z",
            "upgrade": "ask",
        },
    }
    parsed = config.WorkspaceConfig.model_validate(payload)
    config.write_workspace_config(paths.workspace_config_path(workspace_dir), parsed)


def make_fake_git(
    branches: dict[Path, str],
    statuses: dict[Path, str],
    remotes: dict[tuple[Path, str], str],
    tags: dict[Path, set[str]] | None = None,
):
    normalized_branches = {path.resolve(): value for path, value in branches.items()}
    normalized_statuses = {path.resolve(): value for path, value in statuses.items()}
    normalized_remotes = {
        (path.resolve(), branch): value for (path, branch), value in remotes.items()
    }
    normalized_tags = {
        path.resolve(): set(values) for path, values in (tags or {}).items()
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
        if "show-ref" in cmd and "--verify" in cmd and "--quiet" in cmd:
            ref = cmd[-1]
            if ref.startswith("refs/tags/"):
                tag = ref[len("refs/tags/") :]
                tag_set = normalized_tags.get(repo_dir, set())
                if tag in tag_set:
                    return DummyResult(returncode=0, stdout="")
                return DummyResult(returncode=1, stdout="")
        if "ls-remote" in cmd:
            branch = cmd[-1]
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/") :]
            output = normalized_remotes.get((repo_dir, branch), "")
            return DummyResult(returncode=0, stdout=output)
        return DummyResult(returncode=1, stdout="")

    return fake_run


class TestNormalizeOriginUrl(BaseAtelierTestCase):
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


class TestInitProject(BaseAtelierTestCase):
    def test_init_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

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
                config_payload = config.load_project_config(config_path)
                self.assertIsNotNone(config_payload)
                self.assertEqual(config_payload.project.enlistment, enlistment_path)
                self.assertEqual(config_payload.project.origin, NORMALIZED_ORIGIN)
                self.assertEqual(config_payload.project.repo_url, RAW_ORIGIN)
                self.assertTrue(config_payload.branch.pr)
                self.assertEqual(config_payload.branch.history, "manual")
                self.assertEqual(config_payload.editor.edit, ["cursor", "-w"])
                self.assertEqual(config_payload.editor.work, ["cursor"])
                self.assertTrue((project_dir / "templates" / "AGENTS.md").exists())
                self.assertFalse((project_dir / "AGENTS.md").exists())
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
                responses = iter(["", "", "", "", "", ""])

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
                config_payload = config.load_project_config(config_path)
                self.assertIsNotNone(config_payload)
                self.assertEqual(config_payload.editor.edit, ["cursor", "-w"])
                self.assertEqual(config_payload.editor.work, ["cursor"])
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
                responses = iter(["", "", "", "", "cursor -w", "cursor"])

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
                config_payload = config.load_project_config(config_path)
                self.assertIsNotNone(config_payload)
                self.assertEqual(config_payload.editor.edit, ["cursor", "-w"])
                self.assertEqual(config_payload.editor.work, ["cursor"])
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
                responses = iter(["", "", "", "", "", ""])

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
                config_payload = config.load_project_config(config_path)
                self.assertIsNotNone(config_payload)
                self.assertEqual(config_payload.editor.edit, ["nano", "-w"])
                self.assertEqual(config_payload.editor.work, ["nano"])
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
                payload = {
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
                    "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
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
                parsed = config.ProjectConfig.model_validate(payload)
                config.write_project_config(
                    paths.project_config_path(project_dir), parsed
                )

                args = make_init_args(
                    branch_prefix="feat/",
                    branch_pr="false",
                    branch_history="merge",
                    agent="codex",
                    editor_edit="cursor -w",
                    editor_work="cursor",
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
                config_payload = config.load_project_config(config_path)
                self.assertIsNotNone(config_payload)
                self.assertEqual(config_payload.project.enlistment, enlistment_path)
                self.assertEqual(config_payload.project.origin, NORMALIZED_ORIGIN)
                self.assertEqual(config_payload.project.repo_url, RAW_ORIGIN)
                self.assertEqual(config_payload.branch.prefix, "feat/")
                self.assertFalse(config_payload.branch.pr)
                self.assertEqual(config_payload.branch.history, "merge")
                self.assertEqual(config_payload.agent.default, "codex")
                self.assertEqual(config_payload.editor.edit, ["cursor", "-w"])
                self.assertEqual(config_payload.editor.work, ["cursor"])
                self.assertTrue((project_dir / "workspaces").is_dir())
            finally:
                os.chdir(original_cwd)

    def test_init_creates_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

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

                template_path = project_dir / "templates" / "SUCCESS.md"
                self.assertTrue(template_path.exists())
                content = template_path.read_text(encoding="utf-8")
                self.assertIn("SUCCESS.md", content)
                self.assertFalse((project_dir / "templates" / "WORKSPACE.md").exists())
            finally:
                os.chdir(original_cwd)

    def test_legacy_project_config_rejects_legacy_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            legacy_payload = {
                "project": {
                    "enlistment": enlistment_path,
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                },
                "branch": {"prefix": "legacy/", "pr": False, "history": "merge"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "vim", "options": {"vim": ["-w"]}},
                "atelier": {
                    "version": "0.1.0",
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "manual",
                    "managed_files": {"AGENTS.md": "deadbeef"},
                },
            }
            legacy_path = paths.project_config_legacy_path(project_dir)
            legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            with self.assertRaises(SystemExit):
                config.load_project_config(paths.project_config_path(project_dir))
            self.assertTrue(legacy_path.exists())
            self.assertFalse(legacy_path.with_suffix(".json.bak").exists())
            self.assertFalse(paths.project_config_sys_path(project_dir).exists())
            self.assertFalse(paths.project_config_user_path(project_dir).exists())


class TestUpgradeFlags(BaseAtelierTestCase):
    def test_upgrade_flags(self) -> None:
        captured: dict[str, object] = {}

        def fake_upgrade(args: SimpleNamespace) -> None:
            captured["installed"] = args.installed
            captured["dry_run"] = args.dry_run
            captured["yes"] = args.yes
            captured["workspaces"] = args.workspace_names

        runner = CliRunner()
        with patch("atelier.commands.upgrade.upgrade", fake_upgrade):
            result = runner.invoke(
                cli.app,
                ["upgrade", "alpha", "beta", "--installed", "--dry-run", "--yes"],
            )

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(captured["installed"])
        self.assertTrue(captured["dry_run"])
        self.assertTrue(captured["yes"])
        self.assertEqual(captured["workspaces"], ["alpha", "beta"])


class TestUpgradeLegacyEditorMigration(BaseAtelierTestCase):
    def test_upgrade_migrates_legacy_project_user_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

                project_dir.mkdir(parents=True, exist_ok=True)
                system_payload = {
                    "project": {
                        "enlistment": enlistment_path,
                        "origin": NORMALIZED_ORIGIN,
                        "repo_url": RAW_ORIGIN,
                    },
                    "atelier": {
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                }
                system_config = config.ProjectSystemConfig.model_validate(
                    system_payload
                )
                config.write_project_system_config(
                    paths.project_config_sys_path(project_dir), system_config
                )

                user_payload = {
                    "agent": {"default": "codex", "options": {"codex": []}},
                    "editor": {
                        "default": "cursor",
                        "options": {"cursor": ["--wait", "--new-window"]},
                    },
                }
                user_path = paths.project_config_user_path(project_dir)
                user_path.write_text(json.dumps(user_payload), encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    yes=True,
                )
                upgrade_cmd.upgrade(args)

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    updated["editor"]["edit"],
                    ["cursor", "--wait", "--new-window"],
                )
                self.assertEqual(
                    updated["editor"]["work"],
                    ["cursor", "--new-window"],
                )
                self.assertNotIn("default", updated["editor"])
                self.assertNotIn("options", updated["editor"])
                self.assertTrue(user_path.with_suffix(".json.bak").exists())

    def test_upgrade_migrates_legacy_project_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                project_dir.mkdir(parents=True, exist_ok=True)
                legacy_payload = {
                    "project": {
                        "enlistment": enlistment_path,
                        "origin": NORMALIZED_ORIGIN,
                        "repo_url": RAW_ORIGIN,
                    },
                    "branch": {"prefix": "legacy/", "pr": False, "history": "merge"},
                    "agent": {"default": "codex", "options": {"codex": []}},
                    "editor": {
                        "default": "cursor",
                        "options": {"cursor": ["--wait", "--new-window"]},
                    },
                    "atelier": {
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                        "upgrade": "manual",
                    },
                }
                legacy_path = paths.project_config_legacy_path(project_dir)
                legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    yes=True,
                )
                upgrade_cmd.upgrade(args)

                sys_path = paths.project_config_sys_path(project_dir)
                user_path = paths.project_config_user_path(project_dir)
                self.assertTrue(sys_path.exists())
                self.assertTrue(user_path.exists())
                self.assertFalse(legacy_path.exists())
                self.assertTrue(legacy_path.with_suffix(".json.bak").exists())

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    updated["editor"]["edit"],
                    ["cursor", "--wait", "--new-window"],
                )
                self.assertEqual(
                    updated["editor"]["work"],
                    ["cursor", "--new-window"],
                )
                self.assertNotIn("default", updated["editor"])
                self.assertNotIn("options", updated["editor"])


class TestUpgradeWorkspaceConfigRepair(BaseAtelierTestCase):
    def test_upgrade_repairs_missing_workspace_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)

            args = SimpleNamespace(
                workspace_names=[branch],
                installed=False,
                all_projects=False,
                no_projects=True,
                no_workspaces=False,
                dry_run=False,
                yes=True,
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    upgrade_cmd.upgrade(args)
            finally:
                os.chdir(original_cwd)

            sys_path = paths.workspace_config_sys_path(workspace_dir)
            user_path = paths.workspace_config_user_path(workspace_dir)
            self.assertTrue(sys_path.exists())
            self.assertTrue(user_path.exists())
            loaded = config.load_workspace_config(
                paths.workspace_config_path(workspace_dir)
            )
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.workspace.branch, branch)


class TestFindCodexSession(BaseAtelierTestCase):
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
                            "instructions": "agent instructions",
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "agent preamble"},
                            ],
                        },
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": target,
                            "images": [],
                            "local_images": [],
                            "text_elements": [],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("atelier.sessions.Path.home", return_value=home):
                session = sessions_mod.find_codex_session("01TEST", "feat-demo")

            self.assertEqual(session, session_id)


class TestOpenWorkspace(BaseAtelierTestCase):
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
                self.assertTrue((workspace_dir / "PROJECT.md").exists())
                self.assertTrue((workspace_dir / "PERSIST.md").exists())
                self.assertTrue((workspace_dir / "SUCCESS.md").exists())
                self.assertTrue(paths.workspace_config_path(workspace_dir).exists())

                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)

                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Atelier Agent Contract", agents_content)
                self.assertIn("SUCCESS.md", agents_content)
                project_content = (project_dir / "PROJECT.md").read_text(
                    encoding="utf-8"
                )
                workspace_project_content = (workspace_dir / "PROJECT.md").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(workspace_project_content, project_content)
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

    def test_open_resumes_claude_with_continue(self) -> None:
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
                agent={
                    "default": "claude",
                    "options": {"claude": ["--model", "sonnet"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                status_calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_status(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertEqual(
                    status_calls, [["claude", "--model", "sonnet", "--continue"]]
                )
                self.assertFalse(any(cmd and cmd[0] == "claude" for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_resumes_gemini_with_resume_flag(self) -> None:
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
                agent={
                    "default": "gemini",
                    "options": {"gemini": ["--model", "flash"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                status_calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_status(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "gemini"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertEqual(
                    status_calls, [["gemini", "--model", "flash", "--resume"]]
                )
                self.assertFalse(any(cmd and cmd[0] == "gemini" for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_starts_gemini_without_prompt(self) -> None:
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
                agent={
                    "default": "gemini",
                    "options": {"gemini": ["--model", "flash"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_status(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    return DummyResult(returncode=1)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "gemini"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                expected = ["gemini", "--model", "flash"]
                gemini_commands = [
                    cmd for cmd in commands if cmd and cmd[0] == "gemini"
                ]
                self.assertEqual(gemini_commands, [expected])
            finally:
                os.chdir(original_cwd)

    def test_open_resumes_aider_with_chat_history(self) -> None:
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
                agent={
                    "default": "aider",
                    "options": {"aider": ["--model", "gpt-4"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                status_calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_status(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "aider"),
                    ),
                    patch(
                        "atelier.agents.aider_chat_history_path",
                        return_value=Path("/tmp/aider.chat.history.md"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertEqual(
                    status_calls,
                    [["aider", "--model", "gpt-4", "--restore-chat-history"]],
                )
                self.assertFalse(any(cmd and cmd[0] == "aider" for cmd in commands))
            finally:
                os.chdir(original_cwd)

    def test_open_starts_aider_without_prompt_when_no_history(self) -> None:
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
                agent={
                    "default": "aider",
                    "options": {"aider": ["--model", "gpt-4"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                status_calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                def fake_status(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=1)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "aider"),
                    ),
                    patch("atelier.agents.aider_chat_history_path", return_value=None),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                self.assertEqual(status_calls, [])
                aider_commands = [cmd for cmd in commands if cmd and cmd[0] == "aider"]
                self.assertEqual(aider_commands, [["aider", "--model", "gpt-4"]])
            finally:
                os.chdir(original_cwd)

    def test_open_auto_upgrades_project_templates_with_always_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

            project_dir.mkdir(parents=True, exist_ok=True)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)

            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                canonical = templates.agents_template(prefer_installed=True)
            old_text = f"{canonical}\nlegacy\n"
            (templates_dir / "AGENTS.md").write_text(old_text, encoding="utf-8")

            payload = make_open_config(enlistment_path)
            payload["atelier"]["version"] = "9999.0.0"
            payload["atelier"]["upgrade"] = "always"
            payload["atelier"]["managed_files"] = {
                "templates/AGENTS.md": config.hash_text(old_text),
            }
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

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
            finally:
                os.chdir(original_cwd)

            updated = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(updated, canonical)

    def test_open_ask_policy_updates_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

            project_dir.mkdir(parents=True, exist_ok=True)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)

            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                canonical = templates.agents_template(prefer_installed=True)
            old_text = f"{canonical}\nlegacy\n"
            (templates_dir / "AGENTS.md").write_text(old_text, encoding="utf-8")

            payload = make_open_config(enlistment_path)
            payload["atelier"]["version"] = "9999.0.0"
            payload["atelier"]["upgrade"] = "ask"
            payload["atelier"]["managed_files"] = {
                "templates/AGENTS.md": config.hash_text(old_text),
            }
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="y"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            updated = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(updated, canonical)

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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
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

    def test_open_prefers_exact_branch_match_over_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = init_local_repo_without_feature(root)
            subprocess.run(
                ["git", "-C", str(repo_root), "checkout", "-b", "feature/demo"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_root), "checkout", "main"], check=True
            )
            enlistment_path = enlistment_path_for(repo_root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(repo_root)
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
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feature/demo")
                    )

                workspace_branch = "feature/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
                self.assertFalse(
                    paths.workspace_dir_for_branch(
                        project_dir,
                        "scott/feature/demo",
                        workspace_id_for(enlistment_path, "scott/feature/demo"),
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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
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
                self.assertEqual(commands[editor_index][-1], "SUCCESS.md")
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

    def test_open_skips_editor_when_success_md_missing_for_existing_workspace(
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

                self.assertFalse((workspace_dir / "SUCCESS.md").exists())
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
                "atelier": {
                    "version": atelier.__version__,
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "ask",
                },
            }
            parsed = config.WorkspaceConfig.model_validate(payload)
            config.write_workspace_config(
                paths.workspace_config_path(workspace_dir), parsed
            )
            agents_path = workspace_dir / "AGENTS.md"
            workspace_path = workspace_dir / "SUCCESS.md"
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
                    patch("atelier.git.git_tag_exists", return_value=False),
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

    def test_open_continues_when_finalization_tag_present_and_declined(self) -> None:
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
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

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
                    patch("atelier.git.git_tag_exists", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="n"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            self.assertTrue(any(cmd[0] == "codex" for cmd in commands))

    def test_open_removes_finalization_tag_when_confirmed(self) -> None:
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
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                try_commands: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    commands.append(cmd)

                class DummyResult:
                    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
                        self.returncode = returncode
                        self.stdout = stdout

                def fake_try(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    try_commands.append(cmd)
                    return DummyResult(returncode=0, stdout="")

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
                    patch("atelier.git.git_tag_exists", return_value=True),
                    patch("atelier.exec.try_run_command", fake_try),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="y"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            finalization_tag = workspace.finalization_tag_name(workspace_branch)
            self.assertIn(
                ["git", "-C", str(repo_dir), "tag", "-d", finalization_tag],
                try_commands,
            )

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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
            finally:
                os.chdir(original_cwd)

    def test_open_prefers_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            payload = {
                "project": {
                    "enlistment": enlistment_path,
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                },
                "branch": {"prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"edit": ["true"], "work": ["true"]},
                "atelier": {
                    "version": atelier.__version__,
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "ask",
                },
            }
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir()
            success_content = "<!-- success template -->\n"
            legacy_content = "<!-- workspace template -->\n"
            (templates_dir / "SUCCESS.md").write_text(success_content, encoding="utf-8")
            (templates_dir / "WORKSPACE.md").write_text(
                legacy_content, encoding="utf-8"
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
                success_template = workspace_dir / "SUCCESS.md"
                self.assertTrue(success_template.exists())
                self.assertEqual(
                    success_template.read_text(encoding="utf-8"), success_content
                )
                self.assertFalse((workspace_dir / "WORKSPACE.md").exists())
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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertFalse(workspace_config.workspace.branch_pr)
                self.assertEqual(workspace_config.workspace.branch_history, "merge")

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
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                self.assertIsNotNone(workspace_config)
                self.assertEqual(workspace_config.workspace.branch, workspace_branch)
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
            payload = make_open_config(
                enlistment_path,
                branch={"prefix": "scott/", "history": "sideways"},
            )
            legacy_path = paths.project_config_legacy_path(project_dir)
            project_dir.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(json.dumps(payload), encoding="utf-8")

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


class TestWorkCommand(BaseAtelierTestCase):
    def test_work_opens_repo_with_work_editor(self) -> None:
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
                editor={"edit": ["true"], "work": ["code"]},
            )

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_detached(cmd: list[str], cwd: Path | None = None) -> None:
                captured["cmd"] = cmd
                captured["cwd"] = cwd

            with (
                patch(
                    "atelier.commands.work.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.work.git.git_is_repo", return_value=True),
                patch("atelier.commands.work.exec.run_command_detached", fake_detached),
            ):
                work_cmd.open_workspace_repo(
                    SimpleNamespace(workspace_name=workspace_branch)
                )

            self.assertEqual(
                captured["cmd"],
                ["code", str(repo_dir)],
            )
            self.assertEqual(captured["cwd"], workspace_dir)


class TestShellCommand(BaseAtelierTestCase):
    def test_shell_runs_command_in_repo(self) -> None:
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
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                return DummyResult(returncode=5)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with self.assertRaises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=["echo", "hello"],
                        )
                    )

            self.assertEqual(raised.exception.code, 5)
            self.assertEqual(captured["cmd"], ["echo", "hello"])
            self.assertEqual(captured["cwd"], repo_dir)

    def test_shell_uses_override_for_interactive(self) -> None:
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
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                return DummyResult(returncode=0)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with self.assertRaises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell="zsh",
                            command=[],
                        )
                    )

            self.assertEqual(raised.exception.code, 0)
            self.assertEqual(captured["cmd"], ["zsh"])
            self.assertEqual(captured["cwd"], repo_dir)

    def test_exec_requires_command(self) -> None:
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
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
            ):
                with self.assertRaises(SystemExit):
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=[],
                        ),
                        require_command=True,
                    )


class TestConfigCommand(BaseAtelierTestCase):
    def test_config_prompt_updates_project_config(self) -> None:
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
                responses = iter(["team/", "false", "rebase", "codex", "vim -w", "vim"])
                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.branch.prefix, "team/")
                self.assertFalse(updated.branch.pr)
                self.assertEqual(updated.branch.history, "rebase")
                self.assertEqual(updated.editor.edit, ["vim", "-w"])
                self.assertEqual(updated.editor.work, ["vim"])
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_skips_agent_when_only_one_available(self) -> None:
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
                responses = iter(["team/", "false", "rebase", "vim -w", "vim"])
                call_count = {"count": 0}

                def fake_input(_: str) -> str:
                    call_count["count"] += 1
                    return next(responses)

                with (
                    patch("builtins.input", fake_input),
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex",),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.agent.default, "codex")
                self.assertEqual(call_count["count"], 5)
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_retries_invalid_choices(self) -> None:
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
                responses = iter(
                    [
                        "team/",
                        "maybe",
                        "false",
                        "sideways",
                        "merge",
                        "codex",
                        "vim -w",
                        "vim",
                    ]
                )
                call_count = {"count": 0}

                def fake_input(_: str) -> str:
                    call_count["count"] += 1
                    return next(responses)

                with (
                    patch("builtins.input", fake_input),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                self.assertIsNotNone(updated)
                self.assertEqual(call_count["count"], 8)
                self.assertFalse(updated.branch.pr)
                self.assertEqual(updated.branch.history, "merge")
            finally:
                os.chdir(original_cwd)

    def test_config_reset_uses_installed_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            defaults = {
                "branch": {"prefix": "installed/", "pr": False, "history": "squash"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
            }
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                data_dir.mkdir(parents=True, exist_ok=True)
                config.write_json(paths.installed_config_path(), defaults)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("builtins.input", return_value="y"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=False,
                            reset=True,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                self.assertIsNotNone(updated)
                self.assertEqual(updated.branch.prefix, "installed/")
                self.assertFalse(updated.branch.pr)
                self.assertEqual(updated.branch.history, "squash")
                self.assertEqual(updated.editor.edit, ["nano", "-w"])
                self.assertEqual(updated.editor.work, ["nano"])
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_updates_installed_defaults(self) -> None:
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
                responses = iter(
                    ["prefs/", "true", "merge", "codex", "code -w", "code"]
                )
                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=True,
                            prompt=True,
                            reset=False,
                        )
                    )
                with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                    installed_path = paths.installed_config_path()
                stored = json.loads(installed_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["branch"]["prefix"], "prefs/")
                self.assertTrue(stored["branch"]["pr"])
                self.assertEqual(stored["branch"]["history"], "merge")
                self.assertEqual(stored["editor"]["edit"], ["code", "-w"])
                self.assertEqual(stored["editor"]["work"], ["code"])
            finally:
                os.chdir(original_cwd)

    def test_config_edit_updates_user_config(self) -> None:
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
                    temp_path = Path(cmd[-1])
                    payload = {
                        "branch": {
                            "prefix": "edited/",
                            "pr": False,
                            "history": "merge",
                        },
                        "agent": {"default": "codex", "options": {"codex": []}},
                        "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
                        "atelier": {"upgrade": "manual"},
                    }
                    temp_path.write_text(json.dumps(payload), encoding="utf-8")

                with (
                    patch("atelier.commands.config.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=False,
                            reset=False,
                            edit=True,
                        )
                    )
                user_config = config.load_project_user_config(
                    paths.project_config_user_path(project_dir)
                )
                self.assertIsNotNone(user_config)
                self.assertEqual(user_config.branch.prefix, "edited/")
                self.assertFalse(user_config.branch.pr)
                self.assertEqual(user_config.branch.history, "merge")
                self.assertEqual(user_config.editor.edit, ["nano", "-w"])
                self.assertEqual(user_config.editor.work, ["nano"])
                self.assertEqual(user_config.atelier.upgrade, "manual")
            finally:
                os.chdir(original_cwd)


class TestTemplateCommand(BaseAtelierTestCase):
    def test_template_project_prefers_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            installed_template = data_dir / "templates" / "project" / "PROJECT.md"
            installed_template.parent.mkdir(parents=True)
            installed_template.write_text("installed project\n", encoding="utf-8")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_path = project_dir / "PROJECT.md"
            project_path.write_text("project override\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    redirect_stdout(buffer),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "project override")
            finally:
                os.chdir(original_cwd)

    def test_template_project_uses_installed_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            installed_template = data_dir / "templates" / "project" / "PROJECT.md"
            installed_template.parent.mkdir(parents=True)
            installed_template.write_text("installed project\n", encoding="utf-8")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    redirect_stdout(buffer),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "installed project")
            finally:
                os.chdir(original_cwd)

    def test_template_workspace_prefers_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_template = project_dir / "templates" / "SUCCESS.md"
            project_template.parent.mkdir(parents=True, exist_ok=True)
            project_template.write_text("project success\n", encoding="utf-8")
            installed_template = data_dir / "templates" / "workspace" / "SUCCESS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed success\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    redirect_stdout(buffer),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="workspace", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "project success")
            finally:
                os.chdir(original_cwd)

    def test_template_edit_creates_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_path = project_dir / "PROJECT.md"

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    self.assertEqual(
                        temp_path.read_text(encoding="utf-8"), "template stub\n"
                    )
                    temp_path.write_text("edited project\n", encoding="utf-8")

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch(
                        "atelier.templates.project_md_template",
                        return_value="template stub\n",
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=True)
                    )

                self.assertTrue(project_path.exists())
                self.assertEqual(
                    project_path.read_text(encoding="utf-8"), "edited project\n"
                )
                self.assertTrue(calls)
                self.assertNotIn(str(project_path), calls[0])
            finally:
                os.chdir(original_cwd)

    def test_template_edit_creates_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            installed_template = data_dir / "templates" / "workspace" / "SUCCESS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed success\n", encoding="utf-8")
            target_path = project_dir / "templates" / "SUCCESS.md"

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    self.assertEqual(
                        temp_path.read_text(encoding="utf-8"), "installed success\n"
                    )
                    temp_path.write_text("edited success\n", encoding="utf-8")

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="workspace", installed=False, edit=True)
                    )

                self.assertTrue(target_path.exists())
                self.assertEqual(
                    target_path.read_text(encoding="utf-8"), "edited success\n"
                )
                self.assertTrue(calls)
                self.assertNotIn(str(target_path), calls[0])
            finally:
                os.chdir(original_cwd)


class TestEditCommand(BaseAtelierTestCase):
    def test_edit_project_creates_project_md(self) -> None:
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
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch(
                        "atelier.templates.project_md_template",
                        return_value="project stub\n",
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    edit_cmd.edit_files(
                        SimpleNamespace(workspace_name=None, project=True)
                    )

                project_path = project_dir / "PROJECT.md"
                self.assertTrue(project_path.exists())
                self.assertEqual(
                    project_path.read_text(encoding="utf-8"), "project stub\n"
                )
                self.assertTrue(calls)
                self.assertIn(str(project_path), calls[0])
            finally:
                os.chdir(original_cwd)

    def test_edit_workspace_creates_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, branch, enlistment_path)

            template_path = project_dir / "templates" / "SUCCESS.md"
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text("workspace success\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    edit_cmd.edit_files(
                        SimpleNamespace(workspace_name="feat-demo", project=False)
                    )

                success_path = workspace_dir / "SUCCESS.md"
                self.assertTrue(success_path.exists())
                self.assertEqual(
                    success_path.read_text(encoding="utf-8"), "workspace success\n"
                )
                self.assertTrue(calls)
                self.assertIn(str(success_path), calls[0])
            finally:
                os.chdir(original_cwd)
