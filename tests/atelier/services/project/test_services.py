from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atelier.external_registry import PlannerProviderResolution
from atelier.models import ProjectConfig, ProjectSection
from atelier.services import ServiceFailure, ServiceSuccess
from atelier.services.project import (
    ComposeProjectConfigRequest,
    ComposeProjectConfigService,
    InitializeProjectDependencies,
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
    deps = InitializeProjectDependencies(
        resolve_repo_enlistment=lambda cwd: (cwd, "/repo", None, payload.project.origin),
        project_dir_for_enlistment=lambda enlistment, origin: Path("/project-data"),
        project_config_path=lambda project_dir: project_dir / "config.json",
        project_config_user_path=lambda project_dir: project_dir / "config.user.json",
        load_project_config=lambda _path: None,
        load_json=lambda _path: None,
        ensure_project_dirs=lambda _project_dir: None,
        resolve_upgrade_policy=lambda _value: "ask",
        sync_project_skills=lambda *args, **kwargs: SimpleNamespace(action="up_to_date"),
        compose_config_service=compose_service,
        resolve_provider_service=provider_service,
        write_project_config=lambda _path, _cfg: None,
        ensure_project_scaffold=lambda _project_dir: None,
        resolve_beads_root=lambda project_dir, _repo_root: project_dir / ".beads",
        ensure_atelier_store=lambda **kwargs: True,
        ensure_atelier_issue_prefix=lambda **kwargs: True,
        run_bd_command=lambda _args, **kwargs: SimpleNamespace(returncode=0),
        ensure_atelier_types=lambda **kwargs: True,
        list_policy_beads=lambda _role, **kwargs: [],
        extract_policy_body=lambda _issue: "",
        build_combined_policy=lambda planner, worker: ("", False),
        edit_policy_text=lambda text, **kwargs: text,
        split_combined_policy=lambda text: {},
        update_policy_bead=lambda _id, _text, **kwargs: None,
        create_policy_bead=lambda _role, _text, **kwargs: None,
        resolve_agent_home=lambda project_dir, _cfg, **kwargs: project_dir,
        sync_agent_home_policy=lambda _agent_home, **kwargs: None,
        confirm_choice=lambda _text, default=False: False,
    )
    success = InitializeProjectService(deps).run(
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
    failure = InitializeProjectService(
        deps.__class__(**{**deps.__dict__, "compose_config_service": failing})
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
