from __future__ import annotations

from pathlib import Path

from atelier.external_registry import PlannerProviderResolution
from atelier.models import ProjectConfig, ProjectSection
from atelier.services import ServiceFailure, ServiceSuccess
from atelier.services.project import (
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)


def test_resolve_external_provider_service_interactive_selection() -> None:
    selected: dict[str, object] = {}

    def fake_resolver(*args: object, **kwargs: object) -> PlannerProviderResolution:
        return PlannerProviderResolution(
            selected_provider="github",
            available_providers=("github", "linear"),
            github_repo="acme/widgets",
        )

    def fake_select(text: str, options: list[str] | tuple[str, ...], default: str | None) -> str:
        selected["text"] = text
        selected["options"] = list(options)
        selected["default"] = default
        return "none"

    request = ResolveExternalProviderRequest(
        payload=ProjectConfig(
            project=ProjectSection(
                origin="github.com/acme/widgets",
                provider="github",
                auto_export_new=True,
            )
        ),
        repo_root=Path("/repo"),
        agent_name="codex",
        project_data_dir=Path("/project-data"),
        stdin_isatty=True,
        stdout_isatty=True,
    )
    result = ResolveExternalProviderService(
        resolve_provider=fake_resolver,
        choose_provider=fake_select,
        confirm_choice=lambda *_args, **_kwargs: True,
    ).run(request)

    assert isinstance(result, ServiceSuccess)
    assert result.outcome.payload.project.provider is None
    assert result.outcome.payload.project.auto_export_new is False
    assert result.outcome.messages[0] == "Selected external provider: none"
    assert "disabled" in result.outcome.messages[1]
    assert selected["text"] == "External ticket provider"
    assert selected["options"] == ["none", "github", "linear"]
    assert selected["default"] == "github"


def test_resolve_external_provider_service_validation_failure_for_empty_agent() -> None:
    request = ResolveExternalProviderRequest(
        payload=ProjectConfig(),
        repo_root=Path("/repo"),
        agent_name=" ",
        project_data_dir=Path("/project-data"),
        stdin_isatty=False,
        stdout_isatty=False,
    )
    result = ResolveExternalProviderService(
        resolve_provider=lambda *_args, **_kwargs: PlannerProviderResolution(
            selected_provider=None,
            available_providers=(),
            github_repo=None,
        ),
        choose_provider=lambda _text, options, _default: options[0],
        confirm_choice=lambda *_args, **_kwargs: False,
    ).run(request)

    assert isinstance(result, ServiceFailure)
    assert result.code == "validation_failed"
