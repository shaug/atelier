"""Shared helpers for GC operations."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import beads, changesets, git, lifecycle
from .. import exec as exec_util
from .. import log as atelier_log


def log_debug(message: str) -> None:
    atelier_log.debug(f"[gc] {message}")


def log_warning(message: str) -> None:
    atelier_log.warning(f"[gc] {message}")


def run_git_gc_command(args: list[str], *, repo_root: Path, git_path: str) -> tuple[bool, str]:
    log_debug(f"git command start args={' '.join(args)}")
    result = exec_util.try_run_command(
        git.git_command(["-C", str(repo_root), *args], git_path=git_path)
    )
    if result is None:
        log_warning(f"git command missing executable args={' '.join(args)}")
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        log_warning(f"git command failed args={' '.join(args)} detail={detail or 'none'}")
        return False, detail or f"command failed: git {' '.join(args)}"
    log_debug(f"git command ok args={' '.join(args)}")
    return True, (result.stdout or "").strip()


def parse_rfc3339(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def issue_sort_key(issue: dict[str, object]) -> str:
    issue_id = issue.get("id")
    if isinstance(issue_id, str):
        return issue_id
    return ""


def normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def try_show_issue(issue_id: str, *, beads_root: Path, cwd: Path) -> dict[str, object] | None:
    try:
        records = beads.run_bd_issue_records(
            ["show", issue_id], beads_root=beads_root, cwd=cwd, source="gc.try_show_issue"
        )
    except ValueError:
        return None
    if records:
        return records[0].raw
    return None


def branch_lookup_ref(
    repo_root: Path, branch: str, *, git_path: str
) -> tuple[str | None, str | None]:
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/origin/{branch}"
    local = branch if git.git_ref_exists(repo_root, local_ref, git_path=git_path) else None
    remote = (
        f"origin/{branch}" if git.git_ref_exists(repo_root, remote_ref, git_path=git_path) else None
    )
    return local, remote


def branch_integrated_into_target(
    repo_root: Path,
    *,
    branch: str,
    target_ref: str,
    git_path: str,
) -> bool:
    local_ref, remote_ref = branch_lookup_ref(repo_root, branch, git_path=git_path)
    branch_refs = [ref for ref in (local_ref, remote_ref) if ref]
    if not branch_refs:
        return True
    for branch_ref in branch_refs:
        is_ancestor = git.git_is_ancestor(repo_root, branch_ref, target_ref, git_path=git_path)
        if is_ancestor is True:
            return True
        fully_applied = git.git_branch_fully_applied(
            repo_root, target_ref, branch_ref, git_path=git_path
        )
        if fully_applied is True:
            return True
    return False


def changeset_review_state(issue: dict[str, object]) -> str:
    description = issue.get("description")
    review = changesets.parse_review_metadata(description if isinstance(description, str) else "")
    return (review.pr_state or "").strip().lower()


def issue_integrated_sha(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    integrated = fields.get("changeset.integrated_sha")
    if isinstance(integrated, str):
        value = integrated.strip()
        if value and value.lower() != "null":
            return value
    notes = issue.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return None
    for line in notes.splitlines():
        if "changeset.integrated_sha" not in line:
            continue
        _prefix, _sep, suffix = line.partition(":")
        value = suffix.strip()
        if value and value.lower() != "null":
            return value
    return None


def is_merged_closed_changeset(issue: dict[str, object]) -> bool:
    if lifecycle.canonical_lifecycle_status(issue.get("status")) != "closed":
        return False
    if issue_integrated_sha(issue):
        return True
    return changeset_review_state(issue) == "merged"


def workspace_branch_from_labels(labels: set[str]) -> str | None:
    for label in labels:
        if not label.startswith("workspace:"):
            continue
        candidate = label.split(":", 1)[1].strip()
        if candidate:
            return candidate
    return None


def coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None
