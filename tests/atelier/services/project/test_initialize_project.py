from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from atelier.models import ProjectConfig, ProjectSection
from atelier.services import ServiceFailure, ServiceSuccess
from atelier.services.project import (
    ComposeProjectConfigOutcome,
    InitializeProjectDependencies,
    InitializeProjectRequest,
    InitializeProjectService,
    ResolveExternalProviderOutcome,
)


class _ComposeSuccess:
    def __init__(self, payload: ProjectConfig) -> None:
        self.payload = payload
        self.requests: list[object] = []

    def run(self, request: object) -> ServiceSuccess[ComposeProjectConfigOutcome]:
        self.requests.append(request)
        return ServiceSuccess(outcome=ComposeProjectConfigOutcome(payload=self.payload))


class _ResolveSuccess:
    def __init__(self, payload: ProjectConfig) -> None:
        self.payload = payload
        self.requests: list[object] = []

    def run(self, request: object) -> ServiceSuccess[ResolveExternalProviderOutcome]:
        self.requests.append(request)
        return ServiceSuccess(
            outcome=ResolveExternalProviderOutcome(
                payload=self.payload,
                selected_provider="github",
                messages=(
                    "Selected external provider: github",
                    "Default auto-export for new epics/changesets: disabled",
                ),
            )
        )


@dataclass
class _SkillSyncResult:
    action: str


def test_initialize_project_service_orchestrates_expected_steps() -> None:
    payload = ProjectConfig(
        project=ProjectSection(
            origin="github.com/acme/widgets",
            provider="github",
            auto_export_new=False,
        ),
    )
    compose_service = _ComposeSuccess(payload)
    resolve_service = _ResolveSuccess(payload)
    calls: list[tuple[str, object]] = []

    def track(name: str, value: object = None) -> None:
        calls.append((name, value))

    service = InitializeProjectService(
        InitializeProjectDependencies(
            resolve_repo_enlistment=lambda cwd: (
                cwd,
                "/repo",
                "git@github.com:acme/widgets.git",
                "github.com/acme/widgets",
            ),
            project_dir_for_enlistment=lambda enlistment, origin: Path("/project-data"),
            project_config_path=lambda project_dir: project_dir / "config.json",
            project_config_user_path=lambda project_dir: project_dir / "config.user.json",
            load_project_config=lambda path: None,
            load_json=lambda path: None,
            ensure_project_dirs=lambda project_dir: track("ensure_project_dirs", project_dir),
            resolve_upgrade_policy=lambda value, source="atelier.upgrade": "ask",
            sync_project_skills=lambda *args, **kwargs: _SkillSyncResult(action="up_to_date"),
            compose_config_service=compose_service,
            resolve_provider_service=resolve_service,
            write_project_config=lambda path, cfg: track("write_project_config", path),
            ensure_project_scaffold=lambda project_dir: track(
                "ensure_project_scaffold", project_dir
            ),
            resolve_beads_root=lambda project_dir, repo_root: project_dir / ".beads",
            ensure_atelier_store=lambda **kwargs: bool(track("ensure_atelier_store", kwargs)),
            ensure_atelier_issue_prefix=lambda **kwargs: bool(
                track("ensure_atelier_issue_prefix", kwargs)
            ),
            run_bd_command=lambda args, **kwargs: SimpleNamespace(returncode=0),
            ensure_atelier_types=lambda **kwargs: bool(track("ensure_atelier_types", kwargs)),
            list_policy_beads=lambda role, **kwargs: [],
            extract_policy_body=lambda issue: "",
            build_combined_policy=lambda planner, worker: ("", False),
            edit_policy_text=lambda text, **kwargs: text,
            split_combined_policy=lambda text: {},
            update_policy_bead=lambda issue_id, text, **kwargs: None,
            create_policy_bead=lambda role, text, **kwargs: None,
            resolve_agent_home=lambda project_dir, cfg, role: project_dir / role,
            sync_agent_home_policy=lambda agent_home, **kwargs: None,
            confirm_choice=lambda text, default=False: False,
        )
    )
    result = service.run(
        InitializeProjectRequest(
            args=SimpleNamespace(yes=True),
            cwd=Path("/repo"),
            stdin_isatty=False,
            stdout_isatty=False,
        )
    )

    assert isinstance(result, ServiceSuccess)
    assert compose_service.requests
    assert resolve_service.requests
    assert result.outcome.messages[-1] == "Initialized Atelier project"
    assert ("write_project_config", Path("/project-data/config.json")) in calls


def test_initialize_project_service_propagates_compose_failures() -> None:
    called = {"ensure_dirs": False}

    class _ComposeFailure:
        def run(self, request: object) -> ServiceFailure:
            return ServiceFailure(
                code="validation_failed",
                message="bad config",
                recovery_hint="fix args",
            )

    service = InitializeProjectService(
        InitializeProjectDependencies(
            resolve_repo_enlistment=lambda cwd: (cwd, "/repo", None, "github.com/acme/widgets"),
            project_dir_for_enlistment=lambda enlistment, origin: Path("/project-data"),
            project_config_path=lambda project_dir: project_dir / "config.json",
            project_config_user_path=lambda project_dir: project_dir / "config.user.json",
            load_project_config=lambda path: None,
            load_json=lambda path: None,
            ensure_project_dirs=lambda project_dir: called.__setitem__("ensure_dirs", True),
            resolve_upgrade_policy=lambda value, source="atelier.upgrade": "ask",
            sync_project_skills=lambda *args, **kwargs: _SkillSyncResult(action="up_to_date"),
            compose_config_service=_ComposeFailure(),
            resolve_provider_service=_ResolveSuccess(ProjectConfig()),
            write_project_config=lambda path, cfg: None,
            ensure_project_scaffold=lambda project_dir: None,
            resolve_beads_root=lambda project_dir, repo_root: project_dir / ".beads",
            ensure_atelier_store=lambda **kwargs: False,
            ensure_atelier_issue_prefix=lambda **kwargs: False,
            run_bd_command=lambda args, **kwargs: SimpleNamespace(returncode=0),
            ensure_atelier_types=lambda **kwargs: False,
            list_policy_beads=lambda role, **kwargs: [],
            extract_policy_body=lambda issue: "",
            build_combined_policy=lambda planner, worker: ("", False),
            edit_policy_text=lambda text, **kwargs: text,
            split_combined_policy=lambda text: {},
            update_policy_bead=lambda issue_id, text, **kwargs: None,
            create_policy_bead=lambda role, text, **kwargs: None,
            resolve_agent_home=lambda project_dir, cfg, role: project_dir / role,
            sync_agent_home_policy=lambda agent_home, **kwargs: None,
            confirm_choice=lambda text, default=False: False,
        )
    )
    result = service.run(
        InitializeProjectRequest(
            args=SimpleNamespace(yes=True),
            cwd=Path("/repo"),
            stdin_isatty=False,
            stdout_isatty=False,
        )
    )

    assert isinstance(result, ServiceFailure)
    assert result.code == "validation_failed"
    assert called["ensure_dirs"] is False
