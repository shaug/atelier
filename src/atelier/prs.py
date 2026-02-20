"""Helpers for PR-derived lifecycle signals."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from . import git

_GH_TIMEOUT_SECONDS = 20.0
_GH_RETRY_ATTEMPTS = 2
_GH_RETRY_BACKOFF_SECONDS = 0.4
_GH_RETRY_ERROR_MARKERS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "connection aborted",
    "network",
    "tls",
    "rate limit",
    "502",
    "503",
    "504",
)

_PR_LOOKUP_CACHE: dict[tuple[str, str], GithubPrLookup] = {}
_INLINE_FEEDBACK_CACHE: dict[tuple[str, int], str | None] = {}
_UNRESOLVED_THREADS_CACHE: dict[tuple[str, int], int | None] = {}


@dataclass(frozen=True)
class GithubPrLookup:
    """Outcome for a GitHub PR lookup by head branch."""

    outcome: Literal["found", "not_found", "error"]
    payload: dict[str, object] | None = None
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.outcome == "found" and isinstance(self.payload, dict)

    @property
    def failed(self) -> bool:
        return self.outcome == "error"


def github_repo_slug(origin: str | None) -> str | None:
    """Return the GitHub repo slug (owner/name) when applicable."""
    if not origin:
        return None
    normalized = git.normalize_origin_url(origin)
    if normalized.startswith("github.com/"):
        return normalized.split("/", 1)[1]
    return None


def clear_runtime_cache() -> None:
    """Clear in-process PR query caches."""
    _PR_LOOKUP_CACHE.clear()
    _INLINE_FEEDBACK_CACHE.clear()
    _UNRESOLVED_THREADS_CACHE.clear()


def parse_timestamp(value: object) -> datetime | None:
    """Parse ISO-8601 timestamps used by GitHub APIs."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_retryable_message(message: str) -> bool:
    normalized = message.strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _GH_RETRY_ERROR_MARKERS)


def _run(cmd: list[str]) -> str:
    attempts = max(int(_GH_RETRY_ATTEMPTS), 1)
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            last_error = (
                f"Command timed out after {_GH_TIMEOUT_SECONDS:.0f}s: {' '.join(cmd)}"
            )
            if attempt < attempts:
                time.sleep(_GH_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise RuntimeError(last_error) from None

        if result.returncode == 0:
            return result.stdout

        message = result.stderr.strip() or result.stdout.strip()
        last_error = message or f"Command failed: {' '.join(cmd)}"
        if attempt < attempts and _is_retryable_message(last_error):
            time.sleep(_GH_RETRY_BACKOFF_SECONDS * attempt)
            continue
        raise RuntimeError(last_error)

    raise RuntimeError(last_error or f"Command failed: {' '.join(cmd)}")


def _run_json(cmd: list[str]) -> object:
    output = _run(cmd)
    if not output.strip():
        return None
    return json.loads(output)


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _split_repo_slug(repo: str) -> tuple[str, str]:
    owner, sep, name = str(repo).partition("/")
    owner = owner.strip()
    name = name.strip()
    if sep != "/" or not owner or not name:
        raise RuntimeError("repo must be in owner/name format")
    return owner, name


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


def lookup_github_pr_status(repo: str, head: str) -> GithubPrLookup:
    """Return explicit GitHub PR lookup outcome for a head branch."""
    cache_key = (repo, head)
    cached = _PR_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not _gh_available():
        result = GithubPrLookup(outcome="error", error="missing required command: gh")
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    try:
        number = _find_latest_pr_number(repo, head)
    except (RuntimeError, json.JSONDecodeError) as exc:
        result = GithubPrLookup(outcome="error", error=str(exc))
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    if number is None:
        result = GithubPrLookup(outcome="not_found")
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    try:
        payload = _run_json(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,url,state,baseRefName,headRefName,title,body,labels,isDraft,mergedAt,closedAt,updatedAt,reviewDecision,mergeable,reviewRequests,comments,reviews",
            ]
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        result = GithubPrLookup(outcome="error", error=str(exc))
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    if not isinstance(payload, dict):
        result = GithubPrLookup(
            outcome="error", error="Unexpected gh output for PR view"
        )
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    result = GithubPrLookup(outcome="found", payload=payload)
    _PR_LOOKUP_CACHE[cache_key] = result
    return result


def read_github_pr_status(repo: str, head: str) -> dict[str, object] | None:
    """Return GitHub PR metadata for a head branch when available."""
    lookup = lookup_github_pr_status(repo, head)
    if lookup.found:
        return lookup.payload
    return None


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


def _is_bot_author(author: object) -> bool:
    if not isinstance(author, dict):
        return False
    is_bot = author.get("isBot")
    if isinstance(is_bot, bool):
        return is_bot
    author_type = author.get("type")
    if isinstance(author_type, str) and author_type.strip().lower() == "bot":
        return True
    login = author.get("login")
    if isinstance(login, str) and login.strip().lower().endswith("[bot]"):
        return True
    return False


def latest_feedback_timestamp(payload: dict[str, object] | None) -> str | None:
    """Return the latest reviewer feedback timestamp from a PR payload only."""
    if not payload:
        return None
    latest: datetime | None = None

    def include(value: object) -> None:
        nonlocal latest
        parsed = parse_timestamp(value)
        if parsed is None:
            return
        if latest is None or parsed > latest:
            latest = parsed

    comments = payload.get("comments")
    if isinstance(comments, list):
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            author = comment.get("author")
            if _is_bot_author(author):
                continue
            include(comment.get("updatedAt"))
            include(comment.get("createdAt"))

    reviews = payload.get("reviews")
    if isinstance(reviews, list):
        for review in reviews:
            if not isinstance(review, dict):
                continue
            state = str(review.get("state") or "").upper()
            if state not in {"COMMENTED", "CHANGES_REQUESTED"}:
                continue
            author = review.get("author")
            if _is_bot_author(author):
                continue
            include(review.get("updatedAt"))
            include(review.get("submittedAt"))
            include(review.get("createdAt"))

    if latest is None:
        return None
    return _format_timestamp(latest)


def _latest_inline_review_comment_timestamp(repo: str, pr_number: int) -> str | None:
    cache_key = (repo, pr_number)
    if cache_key in _INLINE_FEEDBACK_CACHE:
        return _INLINE_FEEDBACK_CACHE[cache_key]
    try:
        review_comments = _run_json(
            [
                "gh",
                "api",
                f"repos/{repo}/pulls/{pr_number}/comments",
                "--paginate",
            ]
        )
    except (RuntimeError, json.JSONDecodeError):
        _INLINE_FEEDBACK_CACHE[cache_key] = None
        return None
    if not isinstance(review_comments, list):
        _INLINE_FEEDBACK_CACHE[cache_key] = None
        return None
    latest: datetime | None = None
    for comment in review_comments:
        if not isinstance(comment, dict):
            continue
        author = comment.get("user")
        if _is_bot_author(author):
            continue
        for key in ("updated_at", "created_at"):
            parsed = parse_timestamp(comment.get(key))
            if parsed is None:
                continue
            if latest is None or parsed > latest:
                latest = parsed
    if latest is None:
        _INLINE_FEEDBACK_CACHE[cache_key] = None
        return None
    formatted = _format_timestamp(latest)
    _INLINE_FEEDBACK_CACHE[cache_key] = formatted
    return formatted


def latest_feedback_timestamp_with_inline_comments(
    payload: dict[str, object] | None, *, repo: str | None
) -> str | None:
    """Return latest feedback timestamp including inline review comments."""
    latest = latest_feedback_timestamp(payload)
    if not payload or not repo:
        return latest
    pr_number_raw = payload.get("number")
    pr_number = None
    if isinstance(pr_number_raw, int):
        pr_number = pr_number_raw
    elif isinstance(pr_number_raw, str) and pr_number_raw.strip().isdigit():
        pr_number = int(pr_number_raw.strip())
    if pr_number is None:
        return latest
    inline_latest = _latest_inline_review_comment_timestamp(repo, pr_number)
    if inline_latest and (latest is None or inline_latest > latest):
        return inline_latest
    return latest


def unresolved_review_thread_count(repo: str, pr_number: int) -> int | None:
    """Return unresolved inline review thread count for a PR."""
    cache_key = (repo, pr_number)
    if cache_key in _UNRESOLVED_THREADS_CACHE:
        return _UNRESOLVED_THREADS_CACHE[cache_key]
    if not _gh_available():
        _UNRESOLVED_THREADS_CACHE[cache_key] = None
        return None
    if pr_number <= 0:
        _UNRESOLVED_THREADS_CACHE[cache_key] = None
        return None
    try:
        owner, name = _split_repo_slug(repo)
    except RuntimeError:
        _UNRESOLVED_THREADS_CACHE[cache_key] = None
        return None
    query = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()
    cursor: str | None = None
    unresolved = 0
    try:
        while True:
            cmd = [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr_number}",
            ]
            if cursor:
                cmd.extend(["-F", f"cursor={cursor}"])
            payload = _run_json(cmd)
            if not isinstance(payload, dict):
                _UNRESOLVED_THREADS_CACHE[cache_key] = None
                return None
            data = payload.get("data")
            if not isinstance(data, dict):
                _UNRESOLVED_THREADS_CACHE[cache_key] = None
                return None
            repository = data.get("repository")
            if not isinstance(repository, dict):
                _UNRESOLVED_THREADS_CACHE[cache_key] = None
                return None
            pull_request = repository.get("pullRequest")
            if not isinstance(pull_request, dict):
                _UNRESOLVED_THREADS_CACHE[cache_key] = None
                return None
            review_threads = pull_request.get("reviewThreads")
            if not isinstance(review_threads, dict):
                _UNRESOLVED_THREADS_CACHE[cache_key] = None
                return None
            nodes = review_threads.get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    if isinstance(node, dict) and not bool(node.get("isResolved")):
                        unresolved += 1
            page_info = review_threads.get("pageInfo")
            has_next = False
            next_cursor: str | None = None
            if isinstance(page_info, dict):
                has_next = bool(page_info.get("hasNextPage"))
                raw_cursor = page_info.get("endCursor")
                if isinstance(raw_cursor, str) and raw_cursor.strip():
                    next_cursor = raw_cursor.strip()
            if not has_next:
                _UNRESOLVED_THREADS_CACHE[cache_key] = unresolved
                return unresolved
            cursor = next_cursor
            if not cursor:
                _UNRESOLVED_THREADS_CACHE[cache_key] = unresolved
                return unresolved
    except (RuntimeError, json.JSONDecodeError):
        _UNRESOLVED_THREADS_CACHE[cache_key] = None
        return None


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
