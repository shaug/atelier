import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .exec import run_git_command, try_run_command
from .io import die


def strip_git_suffix(path: str) -> str:
    normalized = path.strip().rstrip("/")
    if normalized.lower().endswith(".git"):
        return normalized[: -len(".git")]
    return normalized


def normalize_origin_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""

    scp_match = re.match(r"^(?P<user>[^@]+)@(?P<host>[^:]+):(?P<path>.+)$", raw)
    if scp_match:
        host = scp_match.group("host").lower()
        path = strip_git_suffix(scp_match.group("path").lstrip("/"))
        return f"{host}/{path}"

    if "://" in raw:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        path = strip_git_suffix((parsed.path or "").lstrip("/"))
        if scheme in {"http", "https", "ssh", "git"} and host:
            return f"{host}/{path}"
        if scheme == "file":
            local_path = Path(parsed.path).expanduser().resolve()
            return local_path.as_posix()

    if "/" in raw and " " not in raw:
        head, tail = raw.split("/", 1)
        if "." in head:
            host = head.lower()
            path = strip_git_suffix(tail)
            return f"{host}/{path}"

    local_path = Path(raw).expanduser()
    if not local_path.is_absolute():
        local_path = local_path.resolve()
    return local_path.as_posix()


def git_repo_root(start: Path) -> Path | None:
    result = run_git_command(["git", "-C", str(start), "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    if not resolved:
        return None
    return Path(resolved)


def git_origin_url(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"]
    )
    if result.returncode != 0:
        return None
    origin = result.stdout.strip()
    return origin or None


def resolve_repo_origin(start: Path) -> tuple[Path, str, str]:
    repo_root = git_repo_root(start)
    if not repo_root:
        die("command must be run inside a git repository")
    origin_raw = git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")
    return repo_root, origin_raw, origin


def git_current_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_default_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "symbolic-ref", "refs/remotes/origin/HEAD"]
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix):
            branch = ref[len(prefix) :].strip()
            if branch:
                return branch

    result = run_git_command(["git", "-C", str(repo_dir), "remote", "show", "origin"])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "HEAD branch:" not in line:
                continue
            _, value = line.split(":", 1)
            branch = value.strip()
            if branch:
                return branch

    if git_ref_exists(repo_dir, "refs/heads/main"):
        return "main"
    if git_ref_exists(repo_dir, "refs/heads/master"):
        return "master"

    return git_current_branch(repo_dir)


def git_is_clean(repo_dir: Path) -> bool | None:
    result = run_git_command(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() == ""


def git_upstream_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        [
            "git",
            "-C",
            str(repo_dir),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        ]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_branch_fully_pushed(repo_dir: Path) -> bool | None:
    upstream = git_upstream_branch(repo_dir)
    if not upstream:
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    upstream_head = git_rev_parse(repo_dir, upstream)
    if not head or not upstream_head:
        return None
    return head == upstream_head


def git_has_remote_branch(repo_dir: Path, branch: str) -> bool | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "ls-remote", "--heads", "origin", branch]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() != ""


def git_ref_exists(repo_dir: Path, ref: str) -> bool:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "show-ref", "--verify", "--quiet", ref]
    )
    return result.returncode == 0


def git_rev_parse(repo_dir: Path, ref: str) -> str | None:
    result = run_git_command(["git", "-C", str(repo_dir), "rev-parse", ref])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_is_repo(repo_dir: Path) -> bool:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"]
    )
    return result.returncode == 0


def git_commits_ahead(repo_dir: Path, base: str, branch: str) -> int | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-list", "--count", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def git_commit_messages(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "log", "--format=%B%x1f", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    return [msg.strip() for msg in raw.split("\x1f") if msg.strip()]


def git_diff_name_status(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--name-status", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_diff_stat(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--stat", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_head_matches_remote(repo_dir: Path, branch: str) -> bool | None:
    remote_ref = f"origin/{branch}"
    if not git_ref_exists(repo_dir, f"refs/remotes/{remote_ref}"):
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    remote = git_rev_parse(repo_dir, remote_ref)
    if not head or not remote:
        return None
    return head == remote


def gh_pr_message(repo_dir: Path) -> dict | None:
    result = try_run_command(
        ["gh", "pr", "view", "--json", "title,body,number"], cwd=repo_dir
    )
    if result is None or result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    title = payload.get("title")
    if not title:
        return None
    return {
        "title": title,
        "body": payload.get("body") or "",
        "number": payload.get("number"),
    }
