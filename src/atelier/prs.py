"""Helpers for PR-derived lifecycle signals."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from . import exec as exec_util
from . import git
from .worker.models_boundary import parse_pr_boundary

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
_MERGE_STATE_CONFLICT = {"DIRTY"}
_MERGEABLE_CONFLICT = {"CONFLICTING"}
_MERGE_STATE_UNKNOWN = {"UNKNOWN"}
_MERGEABLE_UNKNOWN = {"UNKNOWN"}

_PR_LOOKUP_CACHE: dict[tuple[str, str], GithubPrLookup] = {}
_INLINE_FEEDBACK_CACHE: dict[tuple[str, int], str | None] = {}
_UNRESOLVED_THREADS_CACHE: dict[tuple[str, int], int | None] = {}


@dataclass(frozen=True)
class GithubClient:
    """Typed command-boundary adapter for GitHub CLI queries."""

    timeout_seconds: float = _GH_TIMEOUT_SECONDS
    retry_attempts: int = _GH_RETRY_ATTEMPTS
    retry_backoff_seconds: float = _GH_RETRY_BACKOFF_SECONDS

    def available(self) -> bool:
        return shutil.which("gh") is not None

    def run(self, cmd: list[str]) -> str:
        attempts = max(int(self.retry_attempts), 1)
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            result = exec_util.run_with_runner(
                exec_util.CommandRequest(
                    argv=tuple(cmd),
                    capture_output=True,
                    text=True,
                    timeout_seconds=self.timeout_seconds,
                )
            )
            if result is None:
                raise RuntimeError("missing required command: gh")
            if result.returncode == 0:
                return result.stdout
            message = (result.stderr or result.stdout or "").strip()
            last_error = message or f"Command failed: {' '.join(cmd)}"
            if attempt < attempts and _is_retryable_message(last_error):
                time.sleep(self.retry_backoff_seconds * attempt)
                continue
            raise RuntimeError(last_error)
        raise RuntimeError(last_error or f"Command failed: {' '.join(cmd)}")

    def run_json(self, cmd: list[str]) -> object:
        output = self.run(cmd)
        if not output.strip():
            return None
        return json.loads(output)


_DEFAULT_GITHUB_CLIENT = GithubClient()


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
    return _DEFAULT_GITHUB_CLIENT.run(cmd)


def _run_json(cmd: list[str]) -> object:
    return _DEFAULT_GITHUB_CLIENT.run_json(cmd)


def _gh_available() -> bool:
    return _DEFAULT_GITHUB_CLIENT.available()


def _split_repo_slug(repo: str) -> tuple[str, str]:
    owner, sep, name = str(repo).partition("/")
    owner = owner.strip()
    name = name.strip()
    if sep != "/" or not owner or not name:
        raise RuntimeError("repo must be in owner/name format")
    return owner, name


@dataclass(frozen=True)
class _HeadBranchPrCandidate:
    number: int
    state: str | None
    updated_at: datetime | None
    closed_at: datetime | None
    merged_at: datetime | None


def _parse_head_branch_candidate(entry: object) -> _HeadBranchPrCandidate | None:
    if not isinstance(entry, dict):
        return None
    raw_number = entry.get("number")
    if not isinstance(raw_number, int):
        return None
    raw_state = entry.get("state")
    state = None
    if isinstance(raw_state, str):
        normalized = raw_state.strip().upper()
        state = normalized or None
    return _HeadBranchPrCandidate(
        number=raw_number,
        state=state,
        updated_at=parse_timestamp(entry.get("updatedAt")),
        closed_at=parse_timestamp(entry.get("closedAt")),
        merged_at=parse_timestamp(entry.get("mergedAt")),
    )


def _list_head_branch_pr_candidates(repo: str, head: str) -> list[_HeadBranchPrCandidate]:
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
            "number,state,updatedAt,closedAt,mergedAt",
        ]
    )
    if not payload:
        return []
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected gh output for PR list")
    candidates: list[_HeadBranchPrCandidate] = []
    for entry in payload:
        candidate = _parse_head_branch_candidate(entry)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate_sort_key(candidate: _HeadBranchPrCandidate) -> tuple[int, datetime, int]:
    timestamp = candidate.updated_at or candidate.closed_at or candidate.merged_at
    has_timestamp = 1 if timestamp is not None else 0
    return (
        has_timestamp,
        timestamp or datetime.min.replace(tzinfo=timezone.utc),
        candidate.number,
    )


def _find_latest_pr_number(repo: str, head: str) -> int | None:
    candidates = _list_head_branch_pr_candidates(repo, head)
    if not candidates:
        return None
    open_candidates = sorted(
        [candidate for candidate in candidates if candidate.state == "OPEN"],
        key=lambda candidate: candidate.number,
    )
    if len(open_candidates) == 1:
        return open_candidates[0].number
    if len(open_candidates) > 1:
        candidate_numbers = ", ".join(f"#{candidate.number}" for candidate in open_candidates)
        raise RuntimeError(
            f"ambiguous PR lookup for head branch {head!r}: multiple open PRs ({candidate_numbers})"
        )
    candidates.sort(key=_candidate_sort_key)
    return candidates[-1].number


def lookup_github_pr_status(repo: str, head: str, *, refresh: bool = False) -> GithubPrLookup:
    """Return explicit GitHub PR lookup outcome for a head branch.

    Args:
        repo: GitHub owner/repo slug.
        head: Head branch name used for lookup.
        refresh: When ``True``, bypass any cached lookup for this branch.

    Returns:
        Lookup outcome for the requested head branch.
    """
    cache_key = (repo, head)
    if refresh:
        _PR_LOOKUP_CACHE.pop(cache_key, None)
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
                "number,url,state,baseRefName,headRefName,title,body,labels,isDraft,"
                "mergedAt,closedAt,updatedAt,reviewDecision,mergeable,mergeStateStatus,"
                "reviewRequests,comments,reviews",
            ]
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        result = GithubPrLookup(outcome="error", error=str(exc))
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    if not isinstance(payload, dict):
        result = GithubPrLookup(outcome="error", error="Unexpected gh output for PR view")
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    try:
        parse_pr_boundary(payload, source=f"{repo}:{head}")
    except ValueError as exc:
        result = GithubPrLookup(outcome="error", error=str(exc))
        _PR_LOOKUP_CACHE[cache_key] = result
        return result
    result = GithubPrLookup(outcome="found", payload=payload)
    _PR_LOOKUP_CACHE[cache_key] = result
    return result


def read_github_pr_status(
    repo: str, head: str, *, refresh: bool = False
) -> dict[str, object] | None:
    """Return GitHub PR metadata for a head branch when available.

    Args:
        repo: GitHub owner/repo slug.
        head: Head branch name used for lookup.
        refresh: When ``True``, bypass any cached lookup for this branch.

    Returns:
        PR payload when found, otherwise ``None``.
    """
    lookup = lookup_github_pr_status(repo, head, refresh=refresh)
    if lookup.found:
        return lookup.payload
    return None


def has_review_requests(payload: dict[str, object] | None) -> bool:
    """Return True if the PR has any review requests."""
    boundary = parse_pr_boundary(payload, source="has_review_requests")
    if boundary is None:
        return False
    for entry in boundary.review_requests:
        requested = entry.requested_reviewer
        if requested is None:
            continue
        if requested.is_bot:
            continue
        if requested.login:
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
    boundary = parse_pr_boundary(payload, source="latest_feedback_timestamp")
    if boundary is None:
        return None
    latest: datetime | None = None

    def include(value: object) -> None:
        nonlocal latest
        parsed = parse_timestamp(value)
        if parsed is None:
            return
        if latest is None or parsed > latest:
            latest = parsed

    for comment in boundary.comments:
        if _is_bot_author(comment.author.model_dump() if comment.author else None):
            continue
        include(comment.updated_at)
        include(comment.created_at)

    for review in boundary.reviews:
        state = str(review.state or "").upper()
        if state not in {"COMMENTED", "CHANGES_REQUESTED"}:
            continue
        if _is_bot_author(review.author.model_dump() if review.author else None):
            continue
        include(review.updated_at)
        include(review.submitted_at)
        include(review.created_at)

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
    boundary = parse_pr_boundary(payload, source="latest_feedback_with_inline")
    latest = latest_feedback_timestamp(payload)
    if boundary is None or not repo:
        return latest
    pr_number = boundary.number
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
    boundary = parse_pr_boundary(payload, source="lifecycle_state")
    if boundary is not None:
        if boundary.merged_at:
            return "merged"
        if boundary.closed_at or str(boundary.state).upper() == "CLOSED":
            return "closed"
        if bool(boundary.is_draft):
            return "draft-pr"
        review_decision = str(boundary.review_decision or "").upper()
        if review_decision == "APPROVED":
            return "approved"
        if review_requested:
            return "in-review"
        return "pr-open"
    if pushed:
        return "pushed"
    return None


def _normalize_pr_signal(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def default_branch_has_merge_conflict(payload: dict[str, object] | None) -> bool | None:
    """Return merge-conflict state for a PR against the default branch.

    Returns ``True`` when deterministic GitHub signals indicate a merge
    conflict, ``False`` when deterministic non-conflict signals are present,
    and ``None`` for missing/transient states.
    """
    boundary = parse_pr_boundary(payload, source="default_branch_has_merge_conflict")
    if boundary is None:
        return None
    merge_state = _normalize_pr_signal(boundary.merge_state_status)
    if merge_state is not None:
        if merge_state in _MERGE_STATE_CONFLICT:
            return True
        if merge_state in _MERGE_STATE_UNKNOWN:
            return None
        return False
    mergeable = _normalize_pr_signal(boundary.mergeable)
    if mergeable is not None:
        if mergeable in _MERGEABLE_CONFLICT:
            return True
        if mergeable in _MERGEABLE_UNKNOWN:
            return None
        return False
    return None
