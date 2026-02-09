"""Resolve external ticket providers and planner environment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import config, git, prs
from .external_providers import ExternalProvider
from .github_issues_provider import GithubIssuesProvider
from .models import ProjectConfig
from .repo_beads_provider import RepoBeadsProvider


@dataclass(frozen=True)
class ExternalProviderContext:
    provider: ExternalProvider
    repo: str | None = None


def _github_repo_from_config(project_config: ProjectConfig) -> str | None:
    candidates = [
        project_config.project.origin,
        project_config.project.repo_url,
    ]
    for candidate in candidates:
        slug = prs.github_repo_slug(candidate)
        if slug:
            return slug
    return None


def _github_repo_from_git(repo_root: Path) -> str | None:
    try:
        _root, _enlistment, _raw, origin = git.resolve_repo_enlistment(repo_root)
    except SystemExit:
        return None
    return prs.github_repo_slug(origin)


def resolve_external_providers(
    project_config: ProjectConfig, repo_root: Path
) -> Sequence[ExternalProviderContext]:
    """Return provider contexts for the current project."""
    provider_contexts: list[ExternalProviderContext] = []

    beads_dir = repo_root / ".beads"
    if beads_dir.exists():
        provider_contexts.append(
            ExternalProviderContext(
                provider=RepoBeadsProvider(repo_root=repo_root, allow_write=True)
            )
        )

    repo_slug = _github_repo_from_config(project_config)
    if repo_slug is None:
        repo_slug = _github_repo_from_git(repo_root)

    if repo_slug and (
        config.is_github_provider(project_config.project.provider) or repo_slug
    ):
        provider_contexts.append(
            ExternalProviderContext(
                provider=GithubIssuesProvider(repo=repo_slug), repo=repo_slug
            )
        )

    return provider_contexts


def planner_provider_environment(
    project_config: ProjectConfig, repo_root: Path
) -> dict[str, str]:
    """Build planner environment variables for external providers."""
    providers = resolve_external_providers(project_config, repo_root)
    if not providers:
        return {}

    env: dict[str, str] = {}
    slugs = [context.provider.slug for context in providers]
    env["ATELIER_EXTERNAL_PROVIDERS"] = ",".join(sorted(set(slugs)))

    for context in providers:
        if isinstance(context.provider, GithubIssuesProvider) and context.repo:
            env["ATELIER_GITHUB_REPO"] = context.repo

    return env
