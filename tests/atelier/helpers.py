# ruff: noqa: E402

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import atelier
import atelier.config as config
import atelier.git as git
import atelier.paths as paths

RAW_ORIGIN = "git@github.com:org/repo.git"
NORMALIZED_ORIGIN = git.normalize_origin_url(RAW_ORIGIN)


def enlistment_path_for(path: Path) -> str:
    return str(path.resolve())


def make_init_args(**overrides: object) -> SimpleNamespace:
    data = {
        "branch_prefix": None,
        "branch_pr": None,
        "branch_history": None,
        "branch_squash_message": None,
        "branch_pr_strategy": None,
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
        payload["project"] = {**payload["project"], **project_override}
    payload.update(overrides)
    return payload


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
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "chore: initial"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", "scott/feat-demo"],
        check=True,
    )
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "feature.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "feat: demo change"],
        check=True,
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
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "chore: initial"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


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
    normalized_tags = {path.resolve(): set(values) for path, values in (tags or {}).items()}

    def fake_run(
        cmd: list[str],
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
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
