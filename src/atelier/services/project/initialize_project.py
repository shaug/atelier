from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict

from ... import agent_home, beads, config, git, paths, policy, project, skills
from ...models import ProjectConfig
from ..result import ServiceResult, ServiceSuccess
from .compose_project_config import ComposeProjectConfigRequest, ComposeProjectConfigService
from .resolve_external_provider import (
    ProviderChooser,
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
    ResolveProvider,
)

PolicyIssue = dict[str, object]
ConfirmChoice = Callable[[str, bool], bool]
BuildProjectConfig = Callable[..., ProjectConfig]


class InitializeProjectRequest(BaseModel):
    args: object
    cwd: Path
    stdin_isatty: bool
    stdout_isatty: bool
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def yes(self) -> bool:
        return bool(getattr(self.args, "yes", False))

    @property
    def interactive(self) -> bool:
        return self.stdin_isatty and self.stdout_isatty and not self.yes


@dataclass(frozen=True)
class InitializeProjectOutcome:
    project_dir: Path
    config_path: Path
    payload: ProjectConfig
    messages: tuple[str, ...]


class InitializeProjectService:
    def __init__(
        self,
        compose_config_service: ComposeProjectConfigService,
        resolve_provider_service: ResolveExternalProviderService,
        confirm_choice: ConfirmChoice,
    ) -> None:
        self._compose_config_service = compose_config_service
        self._resolve_provider_service = resolve_provider_service
        self._confirm_choice = confirm_choice

    @classmethod
    def run_default(
        cls,
        *,
        args: object,
        cwd: Path,
        stdin_isatty: bool,
        stdout_isatty: bool,
        build_config: BuildProjectConfig,
        resolve_provider: ResolveProvider,
        choose_provider: ProviderChooser,
        confirm_choice: ConfirmChoice,
    ) -> ServiceResult[InitializeProjectOutcome]:
        """Run init flow with default service dependencies and request wiring."""
        service = cls(
            compose_config_service=ComposeProjectConfigService(build_config=build_config),
            resolve_provider_service=ResolveExternalProviderService(
                resolve_provider=resolve_provider,
                choose_provider=choose_provider,
                confirm_choice=confirm_choice,
            ),
            confirm_choice=confirm_choice,
        )
        request = InitializeProjectRequest(
            args=args,
            cwd=cwd,
            stdin_isatty=stdin_isatty,
            stdout_isatty=stdout_isatty,
        )
        return service.run(request)

    def run(self, request: InitializeProjectRequest) -> ServiceResult[InitializeProjectOutcome]:
        _root, enlistment, origin_raw, origin = git.resolve_repo_enlistment(request.cwd)
        project_dir = paths.project_dir_for_enlistment(enlistment, origin)
        config_path = paths.project_config_path(project_dir)
        config_payload = config.load_project_config(config_path)
        raw_user = config.load_json(paths.project_config_user_path(project_dir))

        compose = self._compose_config_service.run(
            ComposeProjectConfigRequest(
                existing=config_payload or {},
                enlistment_path=enlistment,
                origin=origin,
                origin_raw=origin_raw,
                args=request.args,
                prompt_missing_only=not bool(config_payload),
                raw_existing=raw_user,
            )
        )
        if compose.success is False:
            return compose
        assert compose.success is True
        payload = compose.outcome.payload

        project.ensure_project_dirs(project_dir)
        messages: list[str] = []
        try:
            sync = skills.sync_project_skills(
                project_dir,
                upgrade_policy=config.resolve_upgrade_policy(payload.atelier.upgrade),
                yes=request.yes,
                interactive=request.interactive,
                prompt_update=lambda message: self._confirm_choice(message, False),
            )
            action = getattr(sync, "action", None)
            if isinstance(action, str) and action in {"installed", "updated", "up_to_date"}:
                messages.append(f"Managed skills: {action}")
        except OSError:
            pass

        provider = self._resolve_provider_service.run(
            ResolveExternalProviderRequest(
                payload=payload,
                repo_root=Path(enlistment),
                agent_name=payload.agent.default,
                project_data_dir=project_dir,
                stdin_isatty=request.stdin_isatty,
                stdout_isatty=request.stdout_isatty,
                yes=request.yes,
            )
        )
        if provider.success is False:
            return provider
        assert provider.success is True
        payload = provider.outcome.payload
        messages.extend(provider.outcome.messages)

        messages.append("Writing project configuration...")
        config.write_project_config(config_path, payload)
        project.ensure_project_scaffold(project_dir)

        beads_root = config.resolve_beads_root(project_dir, Path(enlistment))
        messages.extend(
            (
                "Preparing Beads store...",
                "Priming Beads store...",
                "Ensuring Beads issue types...",
            )
        )
        beads.ensure_atelier_store(beads_root=beads_root, cwd=project_dir)
        beads.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=project_dir)
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=project_dir)
        beads.ensure_atelier_types(beads_root=beads_root, cwd=project_dir)

        if not request.yes and self._confirm_choice("Add project-wide policy for agents?", False):
            self._update_policy(payload, request.cwd, beads_root, project_dir)

        messages.append("Initialized Atelier project")
        return ServiceSuccess(
            InitializeProjectOutcome(project_dir, config_path, payload, tuple(messages))
        )

    def _update_policy(
        self, payload: ProjectConfig, cwd: Path, beads_root: Path, beads_cwd: Path
    ) -> None:
        planner_issue = beads.list_policy_beads(
            policy.ROLE_PLANNER, beads_root=beads_root, cwd=beads_cwd
        )
        worker_issue = beads.list_policy_beads(
            policy.ROLE_WORKER, beads_root=beads_root, cwd=beads_cwd
        )
        planner_body = beads.extract_policy_body(planner_issue[0]) if planner_issue else ""
        worker_body = beads.extract_policy_body(worker_issue[0]) if worker_issue else ""
        combined, split = policy.build_combined_policy(planner_body, worker_body)
        text = policy.edit_policy_text(combined, project_config=payload, cwd=cwd)
        if not text.strip():
            return

        planner_text = worker_text = text
        if split:
            sections = policy.split_combined_policy(text) or {}
            planner_text = sections.get(policy.ROLE_PLANNER, planner_text)
            worker_text = sections.get(policy.ROLE_WORKER, worker_text)

        self._upsert_policy_issue(
            planner_issue, policy.ROLE_PLANNER, planner_text, beads_root, beads_cwd
        )
        self._upsert_policy_issue(
            worker_issue, policy.ROLE_WORKER, worker_text, beads_root, beads_cwd
        )
        planner_home = agent_home.resolve_agent_home(beads_cwd, payload, role=policy.ROLE_PLANNER)
        worker_home = agent_home.resolve_agent_home(beads_cwd, payload, role=policy.ROLE_WORKER)
        policy.sync_agent_home_policy(
            planner_home,
            role=policy.ROLE_PLANNER,
            beads_root=beads_root,
            cwd=beads_cwd,
        )
        policy.sync_agent_home_policy(
            worker_home,
            role=policy.ROLE_WORKER,
            beads_root=beads_root,
            cwd=beads_cwd,
        )

    def _upsert_policy_issue(
        self,
        issues: list[PolicyIssue],
        role: str,
        text: str,
        beads_root: Path,
        beads_cwd: Path,
    ) -> None:
        issue_id = issues[0].get("id") if issues else None
        if isinstance(issue_id, str) and issue_id:
            beads.update_policy_bead(issue_id, text, beads_root=beads_root, cwd=beads_cwd)
            return
        beads.create_policy_bead(role, text, beads_root=beads_root, cwd=beads_cwd)
