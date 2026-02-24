from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atelier.external_registry import PlannerProviderResolution
from atelier.models import ProjectConfig, ProjectSection
from atelier.services import ServiceFailure, ServiceSuccess
from atelier.services.project import (
    ComposeProjectConfigRequest,
    ComposeProjectConfigService,
    InitializeProjectRequest,
    InitializeProjectService,
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)


def test_compose_and_provider_contract_failures() -> None:
    compose = ComposeProjectConfigService(build_config=lambda *args, **kwargs: ProjectConfig())
    compose_result = compose.run(
        ComposeProjectConfigRequest(
            existing={}, enlistment_path=" ", origin=None, origin_raw=None, args=None
        )
    )
    assert isinstance(compose_result, ServiceFailure)
    assert compose_result.code == "validation_failed"

    provider = ResolveExternalProviderService(
        resolve_provider=lambda *args, **kwargs: PlannerProviderResolution(None, (), None),
        choose_provider=lambda _text, options, _default: options[0],
        confirm_choice=lambda _text, _default: False,
    )
    provider_result = provider.run(
        ResolveExternalProviderRequest(
            payload=ProjectConfig(),
            repo_root=Path("/repo"),
            agent_name=" ",
            project_data_dir=Path("/project-data"),
            stdin_isatty=False,
            stdout_isatty=False,
        )
    )
    assert isinstance(provider_result, ServiceFailure)
    assert provider_result.code == "validation_failed"


def test_initialize_project_service_orchestration_and_failure_mapping() -> None:
    payload = ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets"))
    compose_service = SimpleNamespace(
        run=lambda _request: ServiceSuccess(SimpleNamespace(payload=payload))
    )
    provider_service = SimpleNamespace(
        run=lambda _request: ServiceSuccess(
            SimpleNamespace(
                payload=payload,
                messages=(
                    "Selected external provider: github",
                    "Default auto-export for new epics/changesets: disabled",
                ),
            )
        )
    )

    confirm_choice = lambda _text, default=False: False

    with (
        patch(
            "atelier.services.project.initialize_project.git.resolve_repo_enlistment",
            return_value=(Path("/repo"), "/repo", None, payload.project.origin),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_dir_for_enlistment",
            return_value=Path("/project-data"),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_config_path",
            return_value=Path("/project-data/config.json"),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_config_user_path",
            return_value=Path("/project-data/config.user.json"),
        ),
        patch(
            "atelier.services.project.initialize_project.config.load_project_config",
            return_value=None,
        ),
        patch("atelier.services.project.initialize_project.config.load_json", return_value=None),
        patch("atelier.services.project.initialize_project.project.ensure_project_dirs"),
        patch(
            "atelier.services.project.initialize_project.config.resolve_upgrade_policy",
            return_value="ask",
        ),
        patch(
            "atelier.services.project.initialize_project.skills.sync_project_skills",
            return_value=SimpleNamespace(action="up_to_date"),
        ),
        patch("atelier.services.project.initialize_project.config.write_project_config"),
        patch("atelier.services.project.initialize_project.project.ensure_project_scaffold"),
        patch(
            "atelier.services.project.initialize_project.config.resolve_beads_root",
            return_value=Path("/project-data/.beads"),
        ),
        patch("atelier.services.project.initialize_project.beads.ensure_atelier_store"),
        patch("atelier.services.project.initialize_project.beads.ensure_atelier_issue_prefix"),
        patch("atelier.services.project.initialize_project.beads.run_bd_command"),
        patch("atelier.services.project.initialize_project.beads.ensure_atelier_types"),
    ):
        success = InitializeProjectService(
            compose_config_service=compose_service,
            resolve_provider_service=provider_service,
            confirm_choice=confirm_choice,
        ).run(
            InitializeProjectRequest(
                args=SimpleNamespace(yes=True),
                cwd=Path("/repo"),
                stdin_isatty=False,
                stdout_isatty=False,
            )
        )
    assert isinstance(success, ServiceSuccess)
    assert success.outcome.messages[-1] == "Initialized Atelier project"

    failing = SimpleNamespace(
        run=lambda _request: ServiceFailure(code="validation_failed", message="bad config")
    )
    with (
        patch(
            "atelier.services.project.initialize_project.git.resolve_repo_enlistment",
            return_value=(Path("/repo"), "/repo", None, payload.project.origin),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_dir_for_enlistment",
            return_value=Path("/project-data"),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_config_path",
            return_value=Path("/project-data/config.json"),
        ),
        patch(
            "atelier.services.project.initialize_project.paths.project_config_user_path",
            return_value=Path("/project-data/config.user.json"),
        ),
        patch(
            "atelier.services.project.initialize_project.config.load_project_config",
            return_value=None,
        ),
        patch("atelier.services.project.initialize_project.config.load_json", return_value=None),
    ):
        failure = InitializeProjectService(
            compose_config_service=failing,
            resolve_provider_service=provider_service,
            confirm_choice=confirm_choice,
        ).run(
            InitializeProjectRequest(
                args=SimpleNamespace(yes=True),
                cwd=Path("/repo"),
                stdin_isatty=False,
                stdout_isatty=False,
            )
        )
    assert isinstance(failure, ServiceFailure)
    assert failure.code == "validation_failed"
