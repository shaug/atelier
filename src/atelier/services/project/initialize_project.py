from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

from ... import policy
from ...agent_home import AgentHome
from ...models import ProjectConfig
from ..result import ServiceFailure, ServiceResult, ServiceSuccess
from .compose_project_config import ComposeProjectConfigRequest, ComposeProjectConfigService
from .resolve_external_provider import (
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)

PolicyIssue = dict[str, object]
ConfirmChoice = Callable[[str, bool], bool]
SkillUpdatePrompt = Callable[[str], bool]


class SyncSkillsResult(Protocol):
    @property
    def action(self) -> str: ...


class InitializeProjectGateway(Protocol):
    def resolve_repo_enlistment(self, cwd: Path) -> tuple[Path, str, str | None, str | None]: ...

    def project_dir_for_enlistment(self, enlistment: str, origin: str | None) -> Path: ...

    def project_config_path(self, project_dir: Path) -> Path: ...

    def project_config_user_path(self, project_dir: Path) -> Path: ...

    def load_project_config(self, path: Path) -> ProjectConfig | None: ...

    def load_json(self, path: Path) -> dict | None: ...

    def ensure_project_dirs(self, project_dir: Path) -> None: ...

    def resolve_upgrade_policy(self, value: object | None) -> str: ...

    def sync_project_skills(
        self,
        project_dir: Path,
        *,
        upgrade_policy: str,
        yes: bool,
        interactive: bool,
        prompt_update: SkillUpdatePrompt,
    ) -> SyncSkillsResult: ...

    def write_project_config(self, path: Path, payload: ProjectConfig) -> None: ...

    def ensure_project_scaffold(self, project_dir: Path) -> None: ...


class InitializeBeadsGateway(Protocol):
    def resolve_beads_root(self, project_dir: Path, repo_root: Path) -> Path: ...

    def ensure_atelier_store(self, *, beads_root: Path, cwd: Path) -> bool: ...

    def ensure_atelier_issue_prefix(self, *, beads_root: Path, cwd: Path) -> bool: ...

    def run_bd_command(self, args: list[str], *, beads_root: Path, cwd: Path) -> object: ...

    def ensure_atelier_types(self, *, beads_root: Path, cwd: Path) -> bool: ...

    def list_policy_beads(self, role: str, *, beads_root: Path, cwd: Path) -> list[PolicyIssue]: ...

    def extract_policy_body(self, issue: PolicyIssue) -> str: ...

    def update_policy_bead(
        self, issue_id: str, text: str, *, beads_root: Path, cwd: Path
    ) -> None: ...

    def create_policy_bead(
        self, role: str, text: str, *, beads_root: Path, cwd: Path
    ) -> object: ...


class InitializePolicyGateway(Protocol):
    def build_combined_policy(self, planner_text: str, worker_text: str) -> tuple[str, bool]: ...

    def edit_policy_text(self, text: str, *, project_config: ProjectConfig, cwd: Path) -> str: ...

    def split_combined_policy(self, text: str) -> dict[str, str] | None: ...

    def resolve_agent_home(
        self, project_dir: Path, project_config: ProjectConfig, *, role: str
    ) -> AgentHome: ...

    def sync_agent_home_policy(
        self, agent_home: AgentHome, *, role: str, beads_root: Path, cwd: Path
    ) -> None: ...


@dataclass(frozen=True)
class InitializeProjectDependencies:
    project: InitializeProjectGateway
    beads: InitializeBeadsGateway
    policy: InitializePolicyGateway
    compose_config_service: ComposeProjectConfigService
    resolve_provider_service: ResolveExternalProviderService
    confirm_choice: ConfirmChoice


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
    def __init__(self, dependencies: InitializeProjectDependencies) -> None:
        self._deps = dependencies

    def run(self, request: InitializeProjectRequest) -> ServiceResult[InitializeProjectOutcome]:
        _root, enlistment, origin_raw, origin = self._deps.project.resolve_repo_enlistment(
            request.cwd
        )
        project_dir = self._deps.project.project_dir_for_enlistment(enlistment, origin)
        config_path = self._deps.project.project_config_path(project_dir)
        config_payload = self._deps.project.load_project_config(config_path)
        raw_user = self._deps.project.load_json(
            self._deps.project.project_config_user_path(project_dir)
        )

        compose = self._deps.compose_config_service.run(
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
        if isinstance(compose, ServiceFailure):
            return compose
        payload = compose.outcome.payload

        self._deps.project.ensure_project_dirs(project_dir)
        messages: list[str] = []
        try:
            sync = self._deps.project.sync_project_skills(
                project_dir,
                upgrade_policy=self._deps.project.resolve_upgrade_policy(payload.atelier.upgrade),
                yes=request.yes,
                interactive=request.interactive,
                prompt_update=lambda message: self._deps.confirm_choice(message, False),
            )
            action = getattr(sync, "action", None)
            if isinstance(action, str) and action in {"installed", "updated", "up_to_date"}:
                messages.append(f"Managed skills: {action}")
        except OSError:
            pass

        provider = self._deps.resolve_provider_service.run(
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
        if isinstance(provider, ServiceFailure):
            return provider
        payload = provider.outcome.payload
        messages.extend(provider.outcome.messages)

        messages.append("Writing project configuration...")
        self._deps.project.write_project_config(config_path, payload)
        self._deps.project.ensure_project_scaffold(project_dir)

        beads_root = self._deps.beads.resolve_beads_root(project_dir, Path(enlistment))
        messages.extend(
            (
                "Preparing Beads store...",
                "Priming Beads store...",
                "Ensuring Beads issue types...",
            )
        )
        self._deps.beads.ensure_atelier_store(beads_root=beads_root, cwd=project_dir)
        self._deps.beads.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=project_dir)
        self._deps.beads.run_bd_command(["prime"], beads_root=beads_root, cwd=project_dir)
        self._deps.beads.ensure_atelier_types(beads_root=beads_root, cwd=project_dir)

        if not request.yes and self._deps.confirm_choice(
            "Add project-wide policy for agents?", False
        ):
            self._update_policy(payload, request.cwd, beads_root, project_dir)

        messages.append("Initialized Atelier project")
        return ServiceSuccess(
            InitializeProjectOutcome(project_dir, config_path, payload, tuple(messages))
        )

    def _update_policy(
        self, payload: ProjectConfig, cwd: Path, beads_root: Path, beads_cwd: Path
    ) -> None:
        planner_issue = self._deps.beads.list_policy_beads(
            policy.ROLE_PLANNER, beads_root=beads_root, cwd=beads_cwd
        )
        worker_issue = self._deps.beads.list_policy_beads(
            policy.ROLE_WORKER, beads_root=beads_root, cwd=beads_cwd
        )
        planner_body = (
            self._deps.beads.extract_policy_body(planner_issue[0]) if planner_issue else ""
        )
        worker_body = self._deps.beads.extract_policy_body(worker_issue[0]) if worker_issue else ""
        combined, split = self._deps.policy.build_combined_policy(planner_body, worker_body)
        text = self._deps.policy.edit_policy_text(combined, project_config=payload, cwd=cwd)
        if not text.strip():
            return

        planner_text = worker_text = text
        if split:
            sections = self._deps.policy.split_combined_policy(text) or {}
            planner_text = sections.get(policy.ROLE_PLANNER, planner_text)
            worker_text = sections.get(policy.ROLE_WORKER, worker_text)

        self._upsert_policy_issue(
            planner_issue, policy.ROLE_PLANNER, planner_text, beads_root, beads_cwd
        )
        self._upsert_policy_issue(
            worker_issue, policy.ROLE_WORKER, worker_text, beads_root, beads_cwd
        )
        planner_home = self._deps.policy.resolve_agent_home(
            beads_cwd, payload, role=policy.ROLE_PLANNER
        )
        worker_home = self._deps.policy.resolve_agent_home(
            beads_cwd, payload, role=policy.ROLE_WORKER
        )
        self._deps.policy.sync_agent_home_policy(
            planner_home,
            role=policy.ROLE_PLANNER,
            beads_root=beads_root,
            cwd=beads_cwd,
        )
        self._deps.policy.sync_agent_home_policy(
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
            self._deps.beads.update_policy_bead(
                issue_id, text, beads_root=beads_root, cwd=beads_cwd
            )
            return
        self._deps.beads.create_policy_bead(role, text, beads_root=beads_root, cwd=beads_cwd)
