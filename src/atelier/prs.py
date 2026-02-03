"""Helpers for PR-derived lifecycle signals."""

from __future__ import annotations

import json
import shutil
import subprocess

from . import git


def github_repo_slug(origin: str | None) -> str | None:
    """Return the GitHub repo slug (owner/name) when applicable."""
    if not origin:
        return None
    normalized = git.normalize_origin_url(origin)
    if normalized.startswith("github.com/"):
        return normalized.split("/", 1)[1]
    return None


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"Command failed: {' '.join(cmd)}")
    return result.stdout


def _run_json(cmd: list[str]) -> object:
    output = _run(cmd)
    if not output.strip():
        return None
    return json.loads(output)


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _find_latest_pr_number(repo: str, head: str) -> int | None:
    payload = _run_json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            head,
            "--state",
            "all",
            "--json",
            "number",
        ]
    )
    if not payload:
        return None
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected gh output for PR list")
    numbers = sorted(
        {
            entry.get("number")
            for entry in payload
            if isinstance(entry, dict) and isinstance(entry.get("number"), int)
        }
    )
    return numbers[-1] if numbers else None


def read_github_pr_status(repo: str, head: str) -> dict[str, object] | None:
    """Return GitHub PR metadata for a head branch when available."""
    if not _gh_available():
        return None
    try:
        number = _find_latest_pr_number(repo, head)
        if number is None:
            return None
        payload = _run_json(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,url,state,baseRefName,headRefName,title,body,labels,isDraft,mergedAt,closedAt,updatedAt,reviewDecision,mergeable,reviewRequests",
            ]
        )
    except (RuntimeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def has_review_requests(payload: dict[str, object] | None) -> bool:
    """Return True if the PR has any review requests."""
    if not payload:
        return False
    requests = payload.get("reviewRequests")
    if not isinstance(requests, list):
        return False
    for entry in requests:
        if not isinstance(entry, dict):
            continue
        requested = entry.get("requestedReviewer")
        if isinstance(requested, dict):
            is_bot = requested.get("isBot")
            if isinstance(is_bot, bool) and is_bot:
                continue
            login = requested.get("login")
            if isinstance(login, str) and login:
                return True
        elif requested:
            return True
    return False


def lifecycle_state(
    payload: dict[str, object] | None,
    *,
    pushed: bool,
    review_requested: bool,
) -> str | None:
    """Compute a lifecycle state from PR payload and push status."""
    if payload:
        if payload.get("mergedAt"):
            return "merged"
        if payload.get("closedAt") or str(payload.get("state")).upper() == "CLOSED":
            return "closed"
        if bool(payload.get("isDraft")):
            return "draft-pr"
        review_decision = str(payload.get("reviewDecision") or "").upper()
        if review_decision == "APPROVED":
            return "approved"
        if review_requested:
            return "in-review"
        return "pr-open"
    if pushed:
        return "pushed"
    return None
