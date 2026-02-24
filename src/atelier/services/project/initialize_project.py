"""Initialize project orchestration behind a typed service entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ... import policy
from ...agent_home import AgentHome
from ...models import ProjectConfig
from ...skills import ProjectSkillsSyncResult
from ..result import ServiceFailure, ServiceResult, service_success
from .compose_project_config import ComposeProjectConfigRequest, ComposeProjectConfigService
from .resolve_external_provider import (
    ResolveExternalProviderRequest,
    ResolveExternalProviderService,
)


class ResolveRepoEnlistment(Protocol):
    """Typed dependency for enlistment resolution."""

    def __call__(
        self, start: Path, *, git_path: str | None = None
    ) -> tuple[Path, str, str | None, str | None]:
        """Return repository root, enlistment path, raw origin, origin."""
        ...


class ProjectDirForEnlistment(Protocol):
    """Typed dependency for project-dir resolution."""

    def __call__(self, enlistment_path: str, origin: str | None) -> Path:
        """Return project data directory for the enlistment."""
        ...


class ProjectPathLookup(Protocol):
    """Typed dependency for project configuration path lookups."""

    def __call__(self, project_dir: Path) -> Path:
        """Return a project-scoped path."""
        ...


class LoadProjectConfig(Protocol):
    """Typed dependency for reading merged project config."""

    def __call__(self, path: Path) -> ProjectConfig | None:
        """Load merged project config payload."""
        ...


class LoadJson(Protocol):
    """Typed dependency for reading JSON payloads."""

    def __call__(self, path: Path) -> dict | None:
        """Load JSON payload from path."""
        ...


class EnsureProjectDir(Protocol):
    """Typed dependency for ensuring project directories."""

    def __call__(self, project_dir: Path) -> None:
        """Ensure project directories exist."""
        ...


class ResolveUpgradePolicy(Protocol):
    """Typed dependency for upgrade policy normalization."""

    def __call__(self, value: object | None, source: str = "atelier.upgrade") -> str:
        """Normalize/resolve upgrade policy string."""
        ...


class ConfirmChoice(Protocol):
    """Typed dependency for yes/no prompts."""

    def __call__(self, prompt: str, default: bool = False) -> bool:
        """Return confirmation response."""
        ...


class PromptUpdate(Protocol):
    """Typed dependency for optional skill-update confirmation callbacks."""

    def __call__(self, message: str) -> bool:
        """Return whether skill updates should proceed."""
        ...


class SyncProjectSkills(Protocol):
    """Typed dependency for managed-skill synchronization."""

    def __call__(
        self,
        project_dir: Path,
        *,
        upgrade_policy: str,
        yes: bool,
        interactive: bool,
        prompt_update: PromptUpdate | None = None,
        dry_run: bool = False,
    ) -> ProjectSkillsSyncResult:
        """Synchronize project-local managed skills."""
        ...


class WriteProjectConfig(Protocol):
    """Typed dependency for writing merged project config."""

    def __call__(self, path: Path, payload: ProjectConfig) -> None:
        """Write project config payload."""
        ...


class ResolveBeadsRoot(Protocol):
    """Typed dependency for project Beads root resolution."""

    def __call__(self, project_dir: Path, repo_root: Path) -> Path:
        """Resolve planning store path for this project."""
        ...


class BeadsStoreFn(Protocol):
    """Typed dependency for Beads store setup helpers."""

    def __call__(self, *, beads_root: Path, cwd: Path) -> bool:
        """Run Beads setup action."""
        ...


class RunBdCommand(Protocol):
    """Typed dependency for invoking bd commands."""

    def __call__(self, args: list[str], *, beads_root: Path, cwd: Path) -> CompletedProcess[str]:
        """Execute ``bd`` with project-scoped environment."""
        ...


class ListPolicyBeads(Protocol):
    """Typed dependency for listing policy bead records."""

    def __call__(self, role: str, *, beads_root: Path, cwd: Path) -> list[dict]:
        """Return policy bead records for role."""
        ...


class ExtractPolicyBody(Protocol):
    """Typed dependency for extracting policy bead body text."""

    def __call__(self, issue: dict) -> str:
        """Extract policy body text."""
        ...


class BuildCombinedPolicy(Protocol):
    """Typed dependency for combining planner/worker policy text."""

    def __call__(self, planner_text: str, worker_text: str) -> tuple[str, bool]:
        """Return combined policy text and split flag."""
        ...


class EditPolicyText(Protocol):
    """Typed dependency for interactive policy editing."""

    def __call__(self, initial_text: str, *, project_config: ProjectConfig, cwd: Path) -> str:
        """Open editor and return edited policy text."""
        ...


class SplitCombinedPolicy(Protocol):
    """Typed dependency for splitting combined policy text."""

    def __call__(self, text: str) -> dict[str, str] | None:
        """Split combined policy text by role."""
        ...


class UpdatePolicyBead(Protocol):
    """Typed dependency for updating existing policy bead content."""

    def __call__(self, issue_id: str, body: str, *, beads_root: Path, cwd: Path) -> None:
        """Update policy bead body."""
        ...


class CreatePolicyBead(Protocol):
    """Typed dependency for creating new policy bead records."""

    def __call__(self, role: str, body: str, *, beads_root: Path, cwd: Path) -> str:
        """Create policy bead for role."""
        ...


class ResolveAgentHome(Protocol):
    """Typed dependency for role-specific agent-home path lookup."""

    def __call__(
        self,
        project_dir: Path,
        project_config: ProjectConfig,
        *,
        role: str,
        session_key: str | None = None,
    ) -> AgentHome:
        """Resolve agent-home path for role."""
        ...


class SyncAgentHomePolicy(Protocol):
    """Typed dependency for mirroring Beads policy to agent homes."""

    def __call__(self, agent: AgentHome, *, role: str, beads_root: Path, cwd: Path) -> None:
        """Sync policy text to agent-home files."""
        ...


@dataclass(frozen=True)
class InitializeProjectDependencies:
    """Dependency bundle for initialization orchestration service."""

    resolve_repo_enlistment: ResolveRepoEnlistment
    project_dir_for_enlistment: ProjectDirForEnlistment
    project_config_path: ProjectPathLookup
    project_config_user_path: ProjectPathLookup
    load_project_config: LoadProjectConfig
    load_json: LoadJson
    ensure_project_dirs: EnsureProjectDir
    resolve_upgrade_policy: ResolveUpgradePolicy
    sync_project_skills: SyncProjectSkills
    compose_config_service: ComposeProjectConfigService
    resolve_provider_service: ResolveExternalProviderService
    write_project_config: WriteProjectConfig
    ensure_project_scaffold: EnsureProjectDir
    resolve_beads_root: ResolveBeadsRoot
    ensure_atelier_store: BeadsStoreFn
    ensure_atelier_issue_prefix: BeadsStoreFn
    run_bd_command: RunBdCommand
    ensure_atelier_types: BeadsStoreFn
    list_policy_beads: ListPolicyBeads
    extract_policy_body: ExtractPolicyBody
    build_combined_policy: BuildCombinedPolicy
    edit_policy_text: EditPolicyText
    split_combined_policy: SplitCombinedPolicy
    update_policy_bead: UpdatePolicyBead
    create_policy_bead: CreatePolicyBead
    resolve_agent_home: ResolveAgentHome
    sync_agent_home_policy: SyncAgentHomePolicy
    confirm_choice: ConfirmChoice


class InitializeProjectRequest(BaseModel):
    """Input contract for project-init orchestration.

    Attributes:
        args: CLI args object from the command parser.
        cwd: Working directory where init was invoked.
        stdin_isatty: Whether stdin is interactive.
        stdout_isatty: Whether stdout is interactive.
    """

    args: object
    cwd: Path
    stdin_isatty: bool
    stdout_isatty: bool

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def yes(self) -> bool:
        """Return whether init should run without interactive prompts."""

        return bool(getattr(self.args, "yes", False))

    @property
    def interactive(self) -> bool:
        """Return whether init should use interactive prompts."""

        return self.stdin_isatty and self.stdout_isatty and not self.yes


@dataclass(frozen=True)
class InitializeProjectOutcome:
    """Outcome payload for init orchestration.

    Args:
        project_dir: Project data directory.
        config_path: Path to merged project config.
        payload: Final persisted project config payload.
        messages: User-facing output lines in render order.
    """

    project_dir: Path
    config_path: Path
    payload: ProjectConfig
    messages: tuple[str, ...]


class InitializeProjectService:
    """Orchestrate ``atelier init`` side effects via one service entrypoint."""

    def __init__(self, dependencies: InitializeProjectDependencies) -> None:
        """Create the service with explicit collaborators.

        Args:
            dependencies: Typed function bundle for all side-effect boundaries.
        """

        self._deps = dependencies

    def run(self, request: InitializeProjectRequest) -> ServiceResult[InitializeProjectOutcome]:
        """Run full project-init orchestration sequence.

        Args:
            request: Typed initialization request context.

        Returns:
            ``ServiceSuccess`` with render messages and final payload, or
            ``ServiceFailure`` when child services return expected failures.
        """

        _repo_root, enlistment_path, origin_raw, origin = self._deps.resolve_repo_enlistment(
            request.cwd
        )
        project_dir = self._deps.project_dir_for_enlistment(enlistment_path, origin)
        config_path = self._deps.project_config_path(project_dir)
        config_payload = self._deps.load_project_config(config_path)
        user_payload = self._deps.load_json(self._deps.project_config_user_path(project_dir))

        compose_result = self._deps.compose_config_service.run(
            ComposeProjectConfigRequest(
                existing=config_payload or {},
                enlistment_path=enlistment_path,
                origin=origin,
                origin_raw=origin_raw,
                args=request.args,
                prompt_missing_only=not bool(config_payload),
                raw_existing=user_payload,
            )
        )
        if isinstance(compose_result, ServiceFailure):
            return compose_result
        payload = compose_result.outcome.payload

        self._deps.ensure_project_dirs(project_dir)
        messages: list[str] = []
        try:
            upgrade_policy = self._deps.resolve_upgrade_policy(payload.atelier.upgrade)
            sync_result = self._deps.sync_project_skills(
                project_dir,
                upgrade_policy=upgrade_policy,
                yes=request.yes,
                interactive=request.interactive,
                prompt_update=lambda message: self._deps.confirm_choice(message, False),
            )
            if sync_result.action in {"installed", "updated", "up_to_date"}:
                messages.append(f"Managed skills: {sync_result.action}")
        except OSError:
            pass

        provider_result = self._deps.resolve_provider_service.run(
            ResolveExternalProviderRequest(
                payload=payload,
                repo_root=Path(enlistment_path),
                agent_name=payload.agent.default,
                project_data_dir=project_dir,
                stdin_isatty=request.stdin_isatty,
                stdout_isatty=request.stdout_isatty,
                yes=request.yes,
            )
        )
        if isinstance(provider_result, ServiceFailure):
            return provider_result
        payload = provider_result.outcome.payload
        messages.extend(provider_result.outcome.messages)

        messages.append("Writing project configuration...")
        self._deps.write_project_config(config_path, payload)
        self._deps.ensure_project_scaffold(project_dir)

        beads_root = self._deps.resolve_beads_root(project_dir, Path(enlistment_path))
        beads_cwd = project_dir
        messages.append("Preparing Beads store...")
        self._deps.ensure_atelier_store(beads_root=beads_root, cwd=beads_cwd)
        self._deps.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=beads_cwd)
        messages.append("Priming Beads store...")
        self._deps.run_bd_command(["prime"], beads_root=beads_root, cwd=beads_cwd)
        messages.append("Ensuring Beads issue types...")
        self._deps.ensure_atelier_types(beads_root=beads_root, cwd=beads_cwd)

        add_policy = False
        if not request.yes:
            add_policy = self._deps.confirm_choice(
                "Add project-wide policy for agents?",
                default=False,
            )
        if add_policy:
            self._update_policy(
                payload=payload,
                cwd=request.cwd,
                beads_root=beads_root,
                beads_cwd=beads_cwd,
                project_dir=project_dir,
            )

        messages.append("Initialized Atelier project")
        return service_success(
            InitializeProjectOutcome(
                project_dir=project_dir,
                config_path=config_path,
                payload=payload,
                messages=tuple(messages),
            )
        )

    def _update_policy(
        self,
        *,
        payload: ProjectConfig,
        cwd: Path,
        beads_root: Path,
        beads_cwd: Path,
        project_dir: Path,
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
        planner_text = text
        worker_text = text
        if split:
            sections = self._deps.split_combined_policy(text)
            if sections:
                planner_text = sections.get(policy.ROLE_PLANNER, "")
                worker_text = sections.get(policy.ROLE_WORKER, "")
        self._upsert_policy_issue(
            issues=planner_issue,
            role=policy.ROLE_PLANNER,
            text=planner_text,
            beads_root=beads_root,
            beads_cwd=beads_cwd,
        )
        self._upsert_policy_issue(
            issues=worker_issue,
            role=policy.ROLE_WORKER,
            text=worker_text,
            beads_root=beads_root,
            beads_cwd=beads_cwd,
        )
        planner_home = self._deps.resolve_agent_home(
            project_dir,
            payload,
            role=policy.ROLE_PLANNER,
        )
        worker_home = self._deps.resolve_agent_home(
            project_dir,
            payload,
            role=policy.ROLE_WORKER,
        )
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
        *,
        issues: list[dict],
        role: str,
        text: str,
        beads_root: Path,
        beads_cwd: Path,
    ) -> None:
        issue_id = issues[0].get("id") if issues else None
        if isinstance(issue_id, str) and issue_id:
            self._deps.update_policy_bead(
                issue_id,
                text,
                beads_root=beads_root,
                cwd=beads_cwd,
            )
            return
        self._deps.create_policy_bead(
            role,
            text,
            beads_root=beads_root,
            cwd=beads_cwd,
        )
