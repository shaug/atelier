from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from atelier.external_registry import PlannerProviderResolution
from atelier.models import ProjectConfig, ProjectSection
from atelier.services import (
    ExternalCommandFailedError,
    IoFailedError,
    ServiceFailure,
    UnexpectedStateError,
    ValidationFailedError,
)
from atelier.services.project import (
    ComposeProjectConfigOutcome,
    ComposeProjectConfigRequest,
    ComposeProjectConfigService,
    InitializeProjectRequest,
    InitializeProjectService,
    InitProjectArgs,
    ResolveExternalProviderOutcome,
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)


def test_compose_and_provider_contract_failures() -> None:
    def build_config(
        existing: ProjectConfig | dict,
        enlistment_path: str,
        origin: str | None,
        origin_raw: str | None,
        args: InitProjectArgs | None,
        *,
        prompt_missing_only: bool = False,
        raw_existing: dict | None = None,
        allow_editor_empty: bool = False,
    ) -> ProjectConfig:
        del (
            existing,
            enlistment_path,
            origin,
            origin_raw,
            args,
            prompt_missing_only,
            raw_existing,
            allow_editor_empty,
        )
        return ProjectConfig()

    compose = ComposeProjectConfigService(build_config=build_config)
    with pytest.raises(ServiceFailure) as exc_info:
        compose.run(
            ComposeProjectConfigRequest(
                existing={}, enlistment_path=" ", origin=None, origin_raw=None, args=None
            )
        )
    assert exc_info.value.code == "validation_failed"

    def resolve_provider(
        project_config: ProjectConfig,
        repo_root: Path,
        *,
        agent_name: str,
        project_data_dir: Path | None = None,
        agent_home: Path | None = None,
        interactive: bool = True,
        chooser: object | None = None,
    ) -> PlannerProviderResolution:
        del (
            project_config,
            repo_root,
            agent_name,
            project_data_dir,
            agent_home,
            interactive,
            chooser,
        )
        return PlannerProviderResolution(None, (), None)

    def choose_provider(_text: str, options: Sequence[str], _default: str | None) -> str:
        return options[0]

    provider = ResolveExternalProviderService(
        resolve_provider=resolve_provider,
        choose_provider=choose_provider,
        confirm_choice=lambda _text, _default: False,
    )
    with pytest.raises(ServiceFailure) as exc_info:
        provider.run(
            ResolveExternalProviderRequest(
                payload=ProjectConfig(),
                repo_root=Path("/repo"),
                agent_name=" ",
                project_data_dir=Path("/project-data"),
                stdin_isatty=False,
                stdout_isatty=False,
            )
        )
    assert exc_info.value.code == "validation_failed"


def test_compose_and_provider_failures_capture_system_exit_exception() -> None:
    def build_config(
        existing: ProjectConfig | dict,
        enlistment_path: str,
        origin: str | None,
        origin_raw: str | None,
        args: InitProjectArgs | None,
        *,
        prompt_missing_only: bool = False,
        raw_existing: dict | None = None,
        allow_editor_empty: bool = False,
    ) -> ProjectConfig:
        del (
            existing,
            enlistment_path,
            origin,
            origin_raw,
            args,
            prompt_missing_only,
            raw_existing,
            allow_editor_empty,
        )
        raise SystemExit("compose failed")

    compose = ComposeProjectConfigService(build_config=build_config)
    with pytest.raises(ServiceFailure) as exc_info:
        compose.run(
            ComposeProjectConfigRequest(
                existing={},
                enlistment_path="/repo",
                origin=None,
                origin_raw=None,
                args=None,
            )
        )
    assert exc_info.value.code == "external_command_failed"
    assert str(exc_info.value) == "project config composition exited"
    assert exc_info.value.recovery_hint == "compose failed"
    assert isinstance(exc_info.value.__cause__, SystemExit)

    def resolve_provider(
        project_config: ProjectConfig,
        repo_root: Path,
        *,
        agent_name: str,
        project_data_dir: Path | None = None,
        agent_home: Path | None = None,
        interactive: bool = True,
        chooser: object | None = None,
    ) -> PlannerProviderResolution:
        del (
            project_config,
            repo_root,
            agent_name,
            project_data_dir,
            agent_home,
            interactive,
            chooser,
        )
        raise SystemExit("provider failed")

    def choose_provider(_text: str, options: Sequence[str], _default: str | None) -> str:
        return options[0]

    provider = ResolveExternalProviderService(
        resolve_provider=resolve_provider,
        choose_provider=choose_provider,
        confirm_choice=lambda _text, _default: False,
    )
    with pytest.raises(ServiceFailure) as exc_info:
        provider.run(
            ResolveExternalProviderRequest(
                payload=ProjectConfig(),
                repo_root=Path("/repo"),
                agent_name="planner",
                project_data_dir=Path("/project-data"),
                stdin_isatty=False,
                stdout_isatty=False,
            )
        )
    assert exc_info.value.code == "validation_failed"
    assert str(exc_info.value) == "provider resolution failed"
    assert exc_info.value.recovery_hint == "provider failed"
    assert isinstance(exc_info.value.__cause__, SystemExit)


def test_initialize_project_service_orchestration_and_failure_mapping() -> None:
    payload = ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets"))
    compose_service = SimpleNamespace(
        run=lambda _request: ComposeProjectConfigOutcome(payload=payload)
    )
    provider_service = SimpleNamespace(
        run=lambda _request: ResolveExternalProviderOutcome(
            payload=payload,
            selected_provider="github",
            messages=(
                "Selected external provider: github",
                "Default auto-export for new epics/changesets: disabled",
            ),
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
        service = InitializeProjectService(
            compose_config_service=compose_service,
            resolve_provider_service=provider_service,
            confirm_choice=confirm_choice,
        )
        outcome = service(
            InitializeProjectRequest(
                args=InitProjectArgs(yes=True),
                cwd=Path("/repo"),
                stdin_isatty=False,
                stdout_isatty=False,
            )
        )
    assert outcome.messages[-1] == "Initialized Atelier project"

    failing = SimpleNamespace(
        run=lambda _request: (_ for _ in ()).throw(ValidationFailedError("bad config"))
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
        service = InitializeProjectService(
            compose_config_service=failing,
            resolve_provider_service=provider_service,
            confirm_choice=confirm_choice,
        )
        with pytest.raises(ServiceFailure) as exc_info:
            service(
                InitializeProjectRequest(
                    args=InitProjectArgs(yes=True),
                    cwd=Path("/repo"),
                    stdin_isatty=False,
                    stdout_isatty=False,
                )
            )
    assert exc_info.value.code == "validation_failed"


def test_initialize_project_service_maps_boundary_failures_to_stable_service_errors() -> None:
    payload = ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets"))
    compose_service = SimpleNamespace(
        run=lambda _request: ComposeProjectConfigOutcome(payload=payload)
    )
    provider_service = SimpleNamespace(
        run=lambda _request: ResolveExternalProviderOutcome(
            payload=payload,
            selected_provider="github",
            messages=(),
        )
    )

    request = InitializeProjectRequest(
        args=InitProjectArgs(yes=True),
        cwd=Path("/repo"),
        stdin_isatty=False,
        stdout_isatty=False,
    )

    def run_service(
        *,
        write_side_effect: Exception | None = None,
        scaffold_side_effect: Exception | None = None,
        beads_side_effect: BaseException | None = None,
    ) -> None:
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
            patch(
                "atelier.services.project.initialize_project.config.load_json", return_value=None
            ),
            patch("atelier.services.project.initialize_project.project.ensure_project_dirs"),
            patch(
                "atelier.services.project.initialize_project.config.resolve_upgrade_policy",
                return_value="ask",
            ),
            patch(
                "atelier.services.project.initialize_project.skills.sync_project_skills",
                return_value=SimpleNamespace(action="up_to_date"),
            ),
            patch(
                "atelier.services.project.initialize_project.config.write_project_config",
                side_effect=write_side_effect,
            ),
            patch(
                "atelier.services.project.initialize_project.project.ensure_project_scaffold",
                side_effect=scaffold_side_effect,
            ),
            patch(
                "atelier.services.project.initialize_project.config.resolve_beads_root",
                return_value=Path("/project-data/.beads"),
            ),
            patch("atelier.services.project.initialize_project.beads.ensure_atelier_store"),
            patch("atelier.services.project.initialize_project.beads.ensure_atelier_issue_prefix"),
            patch(
                "atelier.services.project.initialize_project.beads.run_bd_command",
                side_effect=beads_side_effect,
            ),
            patch("atelier.services.project.initialize_project.beads.ensure_atelier_types"),
        ):
            service = InitializeProjectService(
                compose_config_service=compose_service,
                resolve_provider_service=provider_service,
                confirm_choice=lambda _text, _default=False: False,
            )
            service(request)

    with pytest.raises(ServiceFailure) as exc_info:
        run_service(write_side_effect=OSError("disk full"))
    assert isinstance(exc_info.value, IoFailedError)
    assert exc_info.value.code == "io_failed"
    assert isinstance(exc_info.value.__cause__, OSError)

    with pytest.raises(ServiceFailure) as exc_info:
        run_service(scaffold_side_effect=RuntimeError("boom"))
    assert isinstance(exc_info.value, UnexpectedStateError)
    assert exc_info.value.code == "unexpected_state"
    assert isinstance(exc_info.value.__cause__, RuntimeError)

    with pytest.raises(ServiceFailure) as exc_info:
        run_service(beads_side_effect=SystemExit("bd failed"))
    assert isinstance(exc_info.value, ExternalCommandFailedError)
    assert exc_info.value.code == "external_command_failed"
    assert exc_info.value.recovery_hint == "bd failed"
    assert isinstance(exc_info.value.__cause__, SystemExit)


def test_initialize_project_service_run_builds_dependencies() -> None:
    captured: dict[str, object] = {}

    def fake_build_config(
        existing: ProjectConfig | dict,
        enlistment_path: str,
        origin: str | None,
        origin_raw: str | None,
        args: object | None,
        *,
        prompt_missing_only: bool = False,
        raw_existing: dict | None = None,
        allow_editor_empty: bool = False,
    ) -> ProjectConfig:
        del (
            existing,
            enlistment_path,
            origin,
            origin_raw,
            args,
            prompt_missing_only,
            raw_existing,
            allow_editor_empty,
        )
        return ProjectConfig()

    def fake_resolve_provider(
        project_config: ProjectConfig,
        repo_root: Path,
        *,
        agent_name: str,
        project_data_dir: Path | None = None,
        agent_home: Path | None = None,
        interactive: bool = True,
        chooser: object | None = None,
    ) -> PlannerProviderResolution:
        del (
            project_config,
            repo_root,
            agent_name,
            project_data_dir,
            agent_home,
            interactive,
            chooser,
        )
        return PlannerProviderResolution(None, (), None)

    def fake_choose_provider(_text: str, options: tuple[str, ...], _default: str | None) -> str:
        return options[0]

    def fake_confirm_choice(_text: str, _default: bool = False) -> bool:
        return False

    def fake_run(self: InitializeProjectService, request: InitializeProjectRequest) -> None:
        captured["service"] = self
        captured["request"] = request
        raise UnexpectedStateError("forced")

    with patch.object(InitializeProjectService, "_run", new=fake_run):
        with pytest.raises(ServiceFailure) as exc_info:
            InitializeProjectService.run(
                args=InitProjectArgs(yes=False),
                cwd=Path("/repo"),
                stdin_isatty=True,
                stdout_isatty=False,
                build_config=fake_build_config,
                resolve_provider=fake_resolve_provider,
                choose_provider=fake_choose_provider,
                confirm_choice=fake_confirm_choice,
            )

    assert exc_info.value.code == "unexpected_state"

    request = captured["request"]
    assert isinstance(request, InitializeProjectRequest)
    assert request.cwd == Path("/repo")
    assert request.stdin_isatty is True
    assert request.stdout_isatty is False
    assert request.yes is False

    service = captured["service"]
    assert isinstance(service, InitializeProjectService)
