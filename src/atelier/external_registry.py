"""Resolve external ticket providers and planner environment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import agents, config, git, paths, prs
from .external_providers import ExternalProvider
from .github_issues_provider import GithubIssuesProvider
from .io import select
from .models import ProjectConfig
from .repo_beads_provider import RepoBeadsProvider

_SKILL_PROVIDER_MAP: dict[str, str] = {
    "linear": "linear",
    "github": "github",
    "github-issues": "github",
    "gh-issues": "github",
    "jira": "jira",
    "asana": "asana",
    "trello": "trello",
    "shortcut": "shortcut",
    "clubhouse": "shortcut",
    "youtrack": "youtrack",
    "clickup": "clickup",
    "gitlab": "gitlab",
    "gitlab-issues": "gitlab",
    "azure-devops": "azure-devops",
    "azuredevops": "azure-devops",
    "azure-boards": "azure-devops",
    "ado": "azure-devops",
}


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


@dataclass(frozen=True)
class TicketProviderSkill:
    """Detected ticket-provider skill metadata."""

    provider: str
    skill_name: str
    path: Path


@dataclass(frozen=True)
class PlannerProviderResolution:
    """Resolved provider selection and candidate list for planner sessions."""

    selected_provider: str | None
    available_providers: tuple[str, ...]
    github_repo: str | None


def _provider_for_skill(skill_dir: Path) -> str | None:
    """Best-effort provider inference for known ticketing skill names."""
    mapped = _SKILL_PROVIDER_MAP.get(skill_dir.name.strip().lower())
    if mapped:
        return mapped
    skill_doc = skill_dir / "SKILL.md"
    if not skill_doc.is_file():
        return None
    try:
        content = skill_doc.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for raw in lines[1:]:
        line = raw.strip()
        if line == "---":
            break
        if not line.lower().startswith("name:"):
            continue
        value = line.split(":", 1)[1].strip().strip("'\"").lower()
        return _SKILL_PROVIDER_MAP.get(value)
    return None


def _skill_roots(
    *,
    agent_name: str,
    project_data_dir: Path | None,
    agent_home: Path | None,
) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            key = path.expanduser().resolve(strict=False)
        except OSError:
            key = path.expanduser()
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    if project_data_dir is not None:
        add(paths.project_skills_dir(project_data_dir))

    project_paths, global_paths = agents.skill_lookup_paths(agent_name)
    if agent_home is not None:
        for rel in project_paths:
            rel_path = Path(rel)
            if rel_path.is_absolute():
                add(rel_path)
            else:
                add(agent_home / rel_path)
    for raw in global_paths:
        add(Path(raw).expanduser())

    return tuple(roots)


def discover_ticket_provider_skills(
    *,
    agent_name: str,
    project_data_dir: Path | None = None,
    agent_home: Path | None = None,
) -> tuple[TicketProviderSkill, ...]:
    """Discover ticket-provider skills from supported skill lookup paths."""
    manifests_by_provider: dict[str, TicketProviderSkill] = {}
    for root in _skill_roots(
        agent_name=agent_name,
        project_data_dir=project_data_dir,
        agent_home=agent_home,
    ):
        if not root.exists() or not root.is_dir():
            continue
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            provider = _provider_for_skill(entry)
            if provider is None:
                continue
            manifest = TicketProviderSkill(
                provider=provider,
                skill_name=entry.name,
                path=entry / "SKILL.md",
            )
            manifests_by_provider.setdefault(manifest.provider, manifest)
    return tuple(sorted(manifests_by_provider.values(), key=lambda item: item.provider))


def discover_ticket_provider_manifests(
    *,
    agent_name: str,
    project_data_dir: Path | None = None,
    agent_home: Path | None = None,
) -> tuple[TicketProviderSkill, ...]:
    """Backward-compatible alias for legacy callers."""
    return discover_ticket_provider_skills(
        agent_name=agent_name,
        project_data_dir=project_data_dir,
        agent_home=agent_home,
    )


def _provider_rank(
    provider: str,
    *,
    configured_provider: str | None,
    repo_signal_order: tuple[str, ...],
    discovered_skills: tuple[str, ...],
) -> tuple[int, int, str]:
    if configured_provider and provider == configured_provider:
        return (0, 0, provider)
    if provider in repo_signal_order:
        return (1, repo_signal_order.index(provider), provider)
    if provider in discovered_skills:
        return (2, discovered_skills.index(provider), provider)
    return (3, 0, provider)


def resolve_planner_provider(
    project_config: ProjectConfig,
    repo_root: Path,
    *,
    agent_name: str,
    project_data_dir: Path | None = None,
    agent_home: Path | None = None,
    interactive: bool = True,
    chooser: Callable[[str, Sequence[str], str | None], str] | None = None,
) -> PlannerProviderResolution:
    """Resolve provider candidates and selected provider for planner runs."""
    repo_signals: list[str] = []
    candidates: set[str] = set()

    manifests = discover_ticket_provider_skills(
        agent_name=agent_name,
        project_data_dir=project_data_dir,
        agent_home=agent_home,
    )
    skill_providers = tuple(manifest.provider for manifest in manifests)
    candidates.update(skill_providers)

    github_repo = _github_repo_from_config(project_config)
    if github_repo is None:
        github_repo = _github_repo_from_git(repo_root)
    if github_repo:
        candidates.add("github")
        repo_signals.append("github")

    if (repo_root / ".beads").exists():
        candidates.add("beads")
        repo_signals.append("beads")

    configured_provider = (project_config.project.provider or "").strip().lower() or None
    available = sorted(
        candidates,
        key=lambda provider: _provider_rank(
            provider,
            configured_provider=configured_provider,
            repo_signal_order=tuple(repo_signals),
            discovered_skills=skill_providers,
        ),
    )

    selected = configured_provider if configured_provider in available else None
    if selected is None:
        if len(available) == 1:
            selected = available[0]
        elif len(available) > 1:
            default = available[0]
            if interactive:
                choose = chooser or select
                selected = choose("External provider", available, default)
            else:
                selected = default

    return PlannerProviderResolution(
        selected_provider=selected,
        available_providers=tuple(available),
        github_repo=github_repo,
    )


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

    if repo_slug and (config.is_github_provider(project_config.project.provider) or repo_slug):
        provider_contexts.append(
            ExternalProviderContext(provider=GithubIssuesProvider(repo=repo_slug), repo=repo_slug)
        )

    return provider_contexts


def planner_provider_environment(
    project_config: ProjectConfig,
    repo_root: Path,
    *,
    selected_provider: str | None = None,
    available_providers: Sequence[str] | None = None,
    github_repo: str | None = None,
) -> dict[str, str]:
    """Build planner environment variables for external providers."""
    resolved_providers = list(available_providers or [])
    if not resolved_providers:
        providers = resolve_external_providers(project_config, repo_root)
        resolved_providers = sorted(
            {
                context.provider.slug
                for context in providers
                if context.provider and context.provider.slug
            }
        )
        if github_repo is None:
            for context in providers:
                if isinstance(context.provider, GithubIssuesProvider) and context.repo:
                    github_repo = context.repo
                    break
    env: dict[str, str] = {}
    if resolved_providers:
        env["ATELIER_EXTERNAL_PROVIDERS"] = ",".join(sorted(set(resolved_providers)))
    configured_provider = (project_config.project.provider or "").strip().lower() or None
    active_provider = selected_provider or configured_provider
    if active_provider is None and resolved_providers:
        if "github" in resolved_providers:
            active_provider = "github"
        else:
            active_provider = sorted(set(resolved_providers))[0]
    if active_provider:
        env["ATELIER_EXTERNAL_PROVIDER"] = active_provider
    if github_repo is None:
        github_repo = _github_repo_from_config(project_config)
        if github_repo is None:
            github_repo = _github_repo_from_git(repo_root)
    if github_repo:
        env["ATELIER_GITHUB_REPO"] = github_repo

    return env
