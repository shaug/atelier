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

    class ProjectGateway:
        def resolve_repo_enlistment(self, cwd: Path) -> tuple[Path, str, str | None, str | None]:
            return cwd, "/repo", None, payload.project.origin

        def project_dir_for_enlistment(self, enlistment: str, origin: str | None) -> Path:
            return Path("/project-data")

        def project_config_path(self, project_dir: Path) -> Path:
            return project_dir / "config.json"

        def project_config_user_path(self, project_dir: Path) -> Path:
            return project_dir / "config.user.json"

        def load_project_config(self, path: Path) -> ProjectConfig | None:
            return None

        def load_json(self, path: Path) -> dict | None:
            return None

        def ensure_project_dirs(self, project_dir: Path) -> None:
            return None

        def resolve_upgrade_policy(self, value: object | None) -> str:
            return "ask"

        def sync_project_skills(
            self,
            project_dir: Path,
            *,
            upgrade_policy: str,
            yes: bool,
            interactive: bool,
            prompt_update,
        ):
            return SimpleNamespace(action="up_to_date")

        def write_project_config(self, path: Path, cfg: ProjectConfig) -> None:
            return None

        def ensure_project_scaffold(self, project_dir: Path) -> None:
            return None

    class BeadsGateway:
        def resolve_beads_root(self, project_dir: Path, repo_root: Path) -> Path:
            return project_dir / ".beads"

        def ensure_atelier_store(self, *, beads_root: Path, cwd: Path) -> bool:
            return True

        def ensure_atelier_issue_prefix(self, *, beads_root: Path, cwd: Path) -> bool:
            return True

        def run_bd_command(self, args: list[str], *, beads_root: Path, cwd: Path):
            return SimpleNamespace(returncode=0)

        def ensure_atelier_types(self, *, beads_root: Path, cwd: Path) -> bool:
            return True

        def list_policy_beads(self, role: str, *, beads_root: Path, cwd: Path) -> list[dict]:
            return []

        def extract_policy_body(self, issue: dict[str, object]) -> str:
            return ""

        def update_policy_bead(
            self, issue_id: str, text: str, *, beads_root: Path, cwd: Path
        ) -> None:
            return None

        def create_policy_bead(self, role: str, text: str, *, beads_root: Path, cwd: Path):
            return None

    class PolicyGateway:
        def build_combined_policy(self, planner: str, worker: str) -> tuple[str, bool]:
            return "", False

        def edit_policy_text(self, text: str, *, project_config: ProjectConfig, cwd: Path) -> str:
            return text

        def split_combined_policy(self, text: str) -> dict[str, str] | None:
            return {}

        def resolve_agent_home(self, project_dir: Path, cfg: ProjectConfig, *, role: str) -> Path:
            return project_dir

        def sync_agent_home_policy(
            self, agent_home: Path, *, role: str, beads_root: Path, cwd: Path
        ) -> None:
            return None

    deps = InitializeProjectDependencies(
        project=ProjectGateway(),
        beads=BeadsGateway(),
        policy=PolicyGateway(),
        compose_config_service=compose_service,
        resolve_provider_service=provider_service,
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
