from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict

from ... import agent_home, beads, config, external_registry, git, paths, policy, project, skills
from ...io import confirm, select
from ...models import ProjectConfig
from ..base import BaseService
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


@dataclass(frozen=True)
class InitProjectArgs:
    """Typed arguments for project initialization.

    The CLI layer maps from the parsed command into this structure before
    calling the service.
    """

    branch_prefix: str | None = None
    branch_pr_mode: str | None = None
    branch_history: str | None = None
    branch_squash_message: str | None = None
    branch_pr_strategy: str | None = None
    agent: str | None = None
    editor_edit: str | None = None
    editor_work: str | None = None
    yes: bool = False


class InitializeProjectRequest(BaseModel):
    args: InitProjectArgs
    cwd: Path
    stdin_isatty: bool
    stdout_isatty: bool
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def yes(self) -> bool:
        return self.args.yes

    @property
    def interactive(self) -> bool:
        return self.stdin_isatty and self.stdout_isatty and not self.yes


@dataclass(frozen=True)
class InitializeProjectOutcome:
    project_dir: Path
    config_path: Path
    payload: ProjectConfig
    messages: tuple[str, ...]


class InitializeProjectService(BaseService[InitializeProjectRequest, InitializeProjectOutcome]):
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
    def run(
        cls,
        *,
        args: InitProjectArgs,
        cwd: Path | None = None,
        stdin_isatty: bool | None = None,
        stdout_isatty: bool | None = None,
        build_config: BuildProjectConfig | None = None,
        resolve_provider: ResolveProvider | None = None,
        choose_provider: ProviderChooser | None = None,
        confirm_choice: ConfirmChoice | None = None,
    ) -> InitializeProjectOutcome:
        """Run init flow with default service dependencies and request wiring."""
        resolved_cwd = cwd or Path.cwd()
        resolved_stdin_isatty = sys.stdin.isatty() if stdin_isatty is None else stdin_isatty
        resolved_stdout_isatty = sys.stdout.isatty() if stdout_isatty is None else stdout_isatty
        resolved_build_config = build_config or config.build_project_config
        resolved_resolve_provider = resolve_provider or external_registry.resolve_planner_provider
        resolved_choose_provider = choose_provider or select
        resolved_confirm_choice = confirm_choice or confirm

        service = cls(
            compose_config_service=ComposeProjectConfigService(build_config=resolved_build_config),
            resolve_provider_service=ResolveExternalProviderService(
                resolve_provider=resolved_resolve_provider,
                choose_provider=resolved_choose_provider,
                confirm_choice=resolved_confirm_choice,
            ),
            confirm_choice=resolved_confirm_choice,
        )
        request = InitializeProjectRequest(
            args=args,
            cwd=resolved_cwd,
            stdin_isatty=resolved_stdin_isatty,
            stdout_isatty=resolved_stdout_isatty,
        )
        return service(request)

    def _run(self, request: InitializeProjectRequest) -> InitializeProjectOutcome:
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
        payload = compose.payload

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
        payload = provider.payload
        messages.extend(provider.messages)

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
        return InitializeProjectOutcome(project_dir, config_path, payload, tuple(messages))

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
