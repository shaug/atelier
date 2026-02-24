from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict

from ... import policy
from ...models import ProjectConfig
from ..result import ServiceFailure, ServiceResult, ServiceSuccess
from .compose_project_config import ComposeProjectConfigRequest, ComposeProjectConfigService
from .resolve_external_provider import (
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)


@dataclass(frozen=True)
class InitializeProjectDependencies:
    resolve_repo_enlistment: Callable[[Path], tuple[Path, str, str | None, str | None]]
    project_dir_for_enlistment: Callable[[str, str | None], Path]
    project_config_path: Callable[[Path], Path]
    project_config_user_path: Callable[[Path], Path]
    load_project_config: Callable[[Path], ProjectConfig | None]
    load_json: Callable[[Path], dict | None]
    ensure_project_dirs: Callable[[Path], None]
    resolve_upgrade_policy: Callable[[object | None], str]
    sync_project_skills: Callable[..., object]
    compose_config_service: ComposeProjectConfigService
    resolve_provider_service: ResolveExternalProviderService
    write_project_config: Callable[[Path, ProjectConfig], None]
    ensure_project_scaffold: Callable[[Path], None]
    resolve_beads_root: Callable[[Path, Path], Path]
    ensure_atelier_store: Callable[..., bool]
    ensure_atelier_issue_prefix: Callable[..., bool]
    run_bd_command: Callable[..., object]
    ensure_atelier_types: Callable[..., bool]
    list_policy_beads: Callable[..., list[dict]]
    extract_policy_body: Callable[[dict], str]
    build_combined_policy: Callable[[str, str], tuple[str, bool]]
    edit_policy_text: Callable[..., str]
    split_combined_policy: Callable[[str], dict[str, str] | None]
    update_policy_bead: Callable[..., None]
    create_policy_bead: Callable[..., object]
    resolve_agent_home: Callable[..., object]
    sync_agent_home_policy: Callable[..., None]
    confirm_choice: Callable[[str, bool], bool]


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
        _root, enlistment, origin_raw, origin = self._deps.resolve_repo_enlistment(request.cwd)
        project_dir = self._deps.project_dir_for_enlistment(enlistment, origin)
        config_path = self._deps.project_config_path(project_dir)
        config_payload = self._deps.load_project_config(config_path)
        raw_user = self._deps.load_json(self._deps.project_config_user_path(project_dir))

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

        self._deps.ensure_project_dirs(project_dir)
        messages: list[str] = []
        try:
            sync = self._deps.sync_project_skills(
                project_dir,
                upgrade_policy=self._deps.resolve_upgrade_policy(payload.atelier.upgrade),
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
        self._deps.write_project_config(config_path, payload)
        self._deps.ensure_project_scaffold(project_dir)

        beads_root = self._deps.resolve_beads_root(project_dir, Path(enlistment))
        messages.extend(
            (
                "Preparing Beads store...",
                "Priming Beads store...",
                "Ensuring Beads issue types...",
            )
        )
        self._deps.ensure_atelier_store(beads_root=beads_root, cwd=project_dir)
        self._deps.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=project_dir)
        self._deps.run_bd_command(["prime"], beads_root=beads_root, cwd=project_dir)
        self._deps.ensure_atelier_types(beads_root=beads_root, cwd=project_dir)

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
        planner_issue = self._deps.list_policy_beads(
            policy.ROLE_PLANNER, beads_root=beads_root, cwd=beads_cwd
        )
        worker_issue = self._deps.list_policy_beads(
            policy.ROLE_WORKER, beads_root=beads_root, cwd=beads_cwd
        )
        planner_body = self._deps.extract_policy_body(planner_issue[0]) if planner_issue else ""
        worker_body = self._deps.extract_policy_body(worker_issue[0]) if worker_issue else ""
        combined, split = self._deps.build_combined_policy(planner_body, worker_body)
        text = self._deps.edit_policy_text(combined, project_config=payload, cwd=cwd)
        if not text.strip():
            return

        planner_text = worker_text = text
        if split:
            sections = self._deps.split_combined_policy(text) or {}
            planner_text = sections.get(policy.ROLE_PLANNER, planner_text)
            worker_text = sections.get(policy.ROLE_WORKER, worker_text)

        self._upsert_policy_issue(
            planner_issue, policy.ROLE_PLANNER, planner_text, beads_root, beads_cwd
        )
        self._upsert_policy_issue(
            worker_issue, policy.ROLE_WORKER, worker_text, beads_root, beads_cwd
        )
        planner_home = self._deps.resolve_agent_home(beads_cwd, payload, role=policy.ROLE_PLANNER)
        worker_home = self._deps.resolve_agent_home(beads_cwd, payload, role=policy.ROLE_WORKER)
        self._deps.sync_agent_home_policy(
            planner_home,
            role=policy.ROLE_PLANNER,
            beads_root=beads_root,
            cwd=beads_cwd,
        )
        self._deps.sync_agent_home_policy(
            worker_home,
            role=policy.ROLE_WORKER,
            beads_root=beads_root,
            cwd=beads_cwd,
        )

    def _upsert_policy_issue(
        self,
        issues: list[dict],
        role: str,
        text: str,
        beads_root: Path,
        beads_cwd: Path,
    ) -> None:
        issue_id = issues[0].get("id") if issues else None
        if isinstance(issue_id, str) and issue_id:
            self._deps.update_policy_bead(issue_id, text, beads_root=beads_root, cwd=beads_cwd)
            return
        self._deps.create_policy_bead(role, text, beads_root=beads_root, cwd=beads_cwd)
