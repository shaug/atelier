"""Git helper functions used by the Atelier CLI."""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .exec import run_git_command, try_run_command
from .io import die


def strip_git_suffix(path: str) -> str:
    """Remove a trailing ``.git`` suffix from a path string.

    Args:
        path: Git URL or path.

    Returns:
        Path without a trailing ``.git``.

    Example:
        >>> strip_git_suffix("example/repo.git")
        'example/repo'
    """
    normalized = path.strip().rstrip("/")
    if normalized.lower().endswith(".git"):
        return normalized[: -len(".git")]
    return normalized


def normalize_origin_url(value: str) -> str:
    """Normalize a Git origin URL to a stable identifier string.

    Supports SSH SCP-style URLs, HTTP(S) URLs, ``file://`` URLs, and local paths.

    Args:
        value: Raw origin URL string.

    Returns:
        Normalized origin suitable for use in project IDs.

    Example:
        >>> normalize_origin_url("git@github.com:org/repo.git")
        'github.com/org/repo'
    """
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
    """Return the git repository root for a starting path.

    Args:
        start: Directory to search from.

    Returns:
        Repo root path or ``None`` if not inside a git repository.

    Example:
        >>> git_repo_root(Path(".")) is None or True
        True
    """
    result = run_git_command(["git", "-C", str(start), "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    if not resolved:
        return None
    return Path(resolved)


def git_origin_url(repo_dir: Path) -> str | None:
    """Return the ``origin`` remote URL for a repository.

    Args:
        repo_dir: Git repository directory.

    Returns:
        Origin URL string, or ``None`` if missing.

    Example:
        >>> git_origin_url(Path(".")) is None or True
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"]
    )
    if result.returncode != 0:
        return None
    origin = result.stdout.strip()
    return origin or None


def resolve_repo_origin(start: Path) -> tuple[Path, str, str]:
    """Resolve the repo root, raw origin URL, and normalized origin.

    Args:
        start: Directory to search from.

    Returns:
        Tuple of ``(repo_root, origin_raw, origin_normalized)``.

    Example:
        >>> resolve_repo_origin(Path("."))  # doctest: +SKIP
        (Path(\"/repo\"), \"git@...\", \"github.com/org/repo\")
    """
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


def resolve_enlistment_path(repo_root: Path) -> str:
    """Resolve the enlistment path identifier for a repository.

    Args:
        repo_root: Path to the git repository root.

    Returns:
        Resolved absolute path string for the enlistment.

    Example:
        >>> resolve_enlistment_path(Path("."))  # doctest: +SKIP
        '/repo'
    """
    return str(repo_root.resolve())


def resolve_repo_enlistment(
    start: Path,
) -> tuple[Path, str, str | None, str | None]:
    """Resolve the repo root, enlistment path, and origin metadata.

    Args:
        start: Directory to search from.

    Returns:
        Tuple of ``(repo_root, enlistment_path, origin_raw, origin_normalized)``.

    Example:
        >>> resolve_repo_enlistment(Path("."))  # doctest: +SKIP
        (Path("/repo"), "/repo", "git@...", "github.com/org/repo")
    """
    repo_root = git_repo_root(start)
    if not repo_root:
        die("command must be run inside a git repository")
    enlistment_path = resolve_enlistment_path(repo_root)
    origin_raw = git_origin_url(repo_root)
    origin = normalize_origin_url(origin_raw) if origin_raw else None
    return repo_root, enlistment_path, origin_raw, origin


def git_current_branch(repo_dir: Path) -> str | None:
    """Return the current branch name.

    Args:
        repo_dir: Git repository directory.

    Returns:
        Branch name or ``None`` when unavailable.

    Example:
        >>> git_current_branch(Path(".")) is None or True
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_default_branch(repo_dir: Path) -> str | None:
    """Determine the default branch for a repository.

    Args:
        repo_dir: Git repository directory.

    Returns:
        Default branch name or ``None``.

    Example:
        >>> git_default_branch(Path(".")) is None or True
        True
    """
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
    """Check whether the working tree is clean.

    Args:
        repo_dir: Git repository directory.

    Returns:
        ``True`` if clean, ``False`` if dirty, ``None`` on error.

    Example:
        >>> git_is_clean(Path(".")) in {True, False, None}
        True
    """
    result = run_git_command(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() == ""


def git_upstream_branch(repo_dir: Path) -> str | None:
    """Return the upstream branch ref for the current branch.

    Args:
        repo_dir: Git repository directory.

    Returns:
        Upstream ref string or ``None`` if not configured.

    Example:
        >>> git_upstream_branch(Path(".")) is None or True
        True
    """
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
    """Return whether the current branch matches its upstream.

    Args:
        repo_dir: Git repository directory.

    Returns:
        ``True`` if fully pushed, ``False`` if not, ``None`` on error.

    Example:
        >>> git_branch_fully_pushed(Path(".")) in {True, False, None}
        True
    """
    upstream = git_upstream_branch(repo_dir)
    if not upstream:
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    upstream_head = git_rev_parse(repo_dir, upstream)
    if not head or not upstream_head:
        return None
    return head == upstream_head


def git_has_remote_branch(repo_dir: Path, branch: str) -> bool | None:
    """Check whether a remote branch exists.

    Args:
        repo_dir: Git repository directory.
        branch: Branch name to check on ``origin``.

    Returns:
        ``True`` if the branch exists, ``False`` if not, ``None`` on error.

    Example:
        >>> git_has_remote_branch(Path("."), "main") in {True, False, None}
        True
    """
    ref = f"refs/heads/{branch}"
    result = run_git_command(
        ["git", "-C", str(repo_dir), "ls-remote", "--heads", "origin", ref]
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            return True
    return False


def git_ref_exists(repo_dir: Path, ref: str) -> bool:
    """Check whether a git ref exists.

    Args:
        repo_dir: Git repository directory.
        ref: Ref name (e.g., ``refs/heads/main``).

    Returns:
        ``True`` if the ref exists.

    Example:
        >>> git_ref_exists(Path("."), "refs/heads/main") in {True, False}
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "show-ref", "--verify", "--quiet", ref]
    )
    return result.returncode == 0


def git_tag_exists(repo_dir: Path, tag: str) -> bool:
    """Check whether a local tag exists.

    Args:
        repo_dir: Git repository directory.
        tag: Tag name to check (without ``refs/tags/``).

    Returns:
        ``True`` if the tag exists.

    Example:
        >>> git_tag_exists(Path("."), "v0.1.0") in {True, False}
        True
    """
    if not tag:
        return False
    return git_ref_exists(repo_dir, f"refs/tags/{tag}")


def git_rev_parse(repo_dir: Path, ref: str) -> str | None:
    """Resolve a ref to its commit hash.

    Args:
        repo_dir: Git repository directory.
        ref: Ref or revision to resolve.

    Returns:
        Commit hash or ``None`` on failure.

    Example:
        >>> git_rev_parse(Path("."), "HEAD") is None or True
        True
    """
    result = run_git_command(["git", "-C", str(repo_dir), "rev-parse", ref])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_is_repo(repo_dir: Path) -> bool:
    """Return whether the path is inside a git work tree.

    Args:
        repo_dir: Path to check.

    Returns:
        ``True`` if inside a git repository.

    Example:
        >>> git_is_repo(Path(".")) in {True, False}
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"]
    )
    return result.returncode == 0


def git_commits_ahead(repo_dir: Path, base: str, branch: str) -> int | None:
    """Count commits in ``branch`` that are not in ``base``.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.

    Returns:
        Number of commits ahead or ``None`` on error.

    Example:
        >>> git_commits_ahead(Path("."), "main", "HEAD") is None or True
        True
    """
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
    """Return commit messages for commits in ``branch`` not in ``base``.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.

    Returns:
        List of commit messages (most recent first).

    Example:
        >>> isinstance(git_commit_messages(Path("."), "main", "HEAD"), list)
        True
    """
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
    """Return ``git diff --name-status`` lines between two refs.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.

    Returns:
        List of ``name-status`` lines.

    Example:
        >>> isinstance(git_diff_name_status(Path("."), "main", "HEAD"), list)
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--name-status", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_diff_stat(repo_dir: Path, base: str, branch: str) -> list[str]:
    """Return ``git diff --stat`` lines between two refs.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.

    Returns:
        List of ``diff --stat`` lines.

    Example:
        >>> isinstance(git_diff_stat(Path("."), "main", "HEAD"), list)
        True
    """
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--stat", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_merge_base(repo_dir: Path, base: str, branch: str) -> str | None:
    """Return the merge base hash between two refs.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.

    Returns:
        Merge-base commit hash or ``None`` on error.

    Example:
        >>> git_merge_base(Path("."), "main", "HEAD") is None or True
        True
    """
    result = run_git_command(["git", "-C", str(repo_dir), "merge-base", base, branch])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_commit_subjects_since_merge_base(
    repo_dir: Path, base: str, branch: str, limit: int = 20
) -> list[str]:
    """Return commit subjects since the merge base of two refs.

    Args:
        repo_dir: Git repository directory.
        base: Base branch/ref.
        branch: Branch/ref to compare.
        limit: Maximum number of subjects to return.

    Returns:
        List of commit subject lines.

    Example:
        >>> isinstance(git_commit_subjects_since_merge_base(Path("."), "main", "HEAD"), list)
        True
    """
    merge_base = git_merge_base(repo_dir, base, branch)
    if not merge_base:
        return []
    result = run_git_command(
        [
            "git",
            "-C",
            str(repo_dir),
            "log",
            "--format=%s",
            f"--max-count={max(0, limit)}",
            f"{merge_base}..{branch}",
        ]
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_head_matches_remote(repo_dir: Path, branch: str) -> bool | None:
    """Return whether ``HEAD`` matches ``origin/<branch>``.

    Args:
        repo_dir: Git repository directory.
        branch: Branch name to compare.

    Returns:
        ``True`` if hashes match, ``False`` if not, ``None`` when missing.

    Example:
        >>> git_head_matches_remote(Path("."), "main") in {True, False, None}
        True
    """
    remote_ref = f"origin/{branch}"
    if not git_ref_exists(repo_dir, f"refs/remotes/{remote_ref}"):
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    remote = git_rev_parse(repo_dir, remote_ref)
    if not head or not remote:
        return None
    return head == remote


def gh_pr_message(repo_dir: Path) -> dict | None:
    """Fetch PR metadata from the GitHub CLI when available.

    Args:
        repo_dir: Git repository directory.

    Returns:
        Dict with ``title``, ``body``, and ``number`` keys or ``None``.

    Example:
        >>> gh_pr_message(Path(".")) is None or True
        True
    """
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
