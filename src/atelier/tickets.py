"""Ticket context helpers for Atelier."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import exec as exec_util
from . import git
from .io import warn

_GH_URL_RE = re.compile(
    r"https?://github\.com/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)"
)
_GH_REF_RE = re.compile(r"^(?P<repo>[^#\s]+)#(?P<number>\d+)$")


@dataclass(frozen=True)
class TicketContext:
    """Resolved ticket context for AI helpers."""

    ref: str
    provider: str | None
    project: str | None
    title: str | None
    body: str | None
    url: str | None


def resolve_ticket_context(
    ref: str,
    *,
    provider: str | None,
    default_project: str | None,
    project_origin: str | None,
    project_repo_url: str | None,
) -> TicketContext:
    """Resolve ticket context best-effort for AI helpers."""
    normalized_provider = (provider or "").strip().lower() or None
    project = _resolve_github_project(
        default_project=default_project,
        project_origin=project_origin,
        project_repo_url=project_repo_url,
    )
    if normalized_provider == "github" and git.gh_available():
        repo, number = _parse_github_issue_ref(ref, project)
        if repo and number:
            context = _gh_issue_context(repo, number, ref)
            if context is not None:
                return context
    return TicketContext(
        ref=ref,
        provider=normalized_provider,
        project=project,
        title=None,
        body=None,
        url=None,
    )


def format_ticket_context(context: TicketContext) -> str:
    """Render ticket context into a plain-text prompt block."""
    lines = [f"Ticket: {context.ref}"]
    if context.provider:
        lines.append(f"Provider: {context.provider}")
    if context.project:
        lines.append(f"Project: {context.project}")
    if context.title:
        lines.append(f"Title: {context.title}")
    if context.url:
        lines.append(f"URL: {context.url}")
    if context.body:
        lines.append("Body:")
        lines.append(context.body)
    return "\n".join(lines)


def _resolve_github_project(
    *,
    default_project: str | None,
    project_origin: str | None,
    project_repo_url: str | None,
) -> str | None:
    if default_project:
        return default_project
    for value in (project_origin, project_repo_url):
        if not value:
            continue
        normalized = git.normalize_origin_url(value)
        if normalized.startswith("github.com/"):
            return normalized.split("github.com/", 1)[1]
    return None


def _parse_github_issue_ref(
    ref: str, default_repo: str | None
) -> tuple[str | None, str | None]:
    raw = ref.strip()
    match = _GH_URL_RE.search(raw)
    if match:
        return match.group("repo"), match.group("number")
    match = _GH_REF_RE.match(raw)
    if match:
        return match.group("repo"), match.group("number")
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        match = _GH_URL_RE.search(raw)
        if match:
            return match.group("repo"), match.group("number")
    if raw.isdigit() and default_repo:
        return default_repo, raw
    return None, None


def _gh_issue_context(repo: str, number: str, ref: str) -> TicketContext | None:
    result = exec_util.try_run_command(
        [
            "gh",
            "issue",
            "view",
            number,
            "--repo",
            repo,
            "--json",
            "title,body,url,number",
        ]
    )
    if result is None or result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        warn("failed to parse ticket metadata from gh")
        return None
    title = payload.get("title")
    if not title:
        return None
    return TicketContext(
        ref=ref,
        provider="github",
        project=repo,
        title=str(title),
        body=str(payload.get("body") or ""),
        url=str(payload.get("url") or ""),
    )
