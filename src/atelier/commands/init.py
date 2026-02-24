"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

import sys
from pathlib import Path
from typing import Callable

from .. import (
    agent_home,
    beads,
    config,
    external_registry,
    git,
    paths,
    policy,
    project,
    skills,
)
from ..io import confirm, die, say, select
from ..models import ProjectConfig
from ..services import ServiceFailure
from ..services.project import (
    ComposeProjectConfigService,
    InitializeProjectDependencies,
    InitializeProjectRequest,
    InitializeProjectService,
    ResolveExternalProviderService,
)


class _ProjectGateway:
    def resolve_repo_enlistment(self, cwd: Path) -> tuple[Path, str, str | None, str | None]:
        return git.resolve_repo_enlistment(cwd)

    def project_dir_for_enlistment(self, enlistment: str, origin: str | None) -> Path:
        return paths.project_dir_for_enlistment(enlistment, origin)

    def project_config_path(self, project_dir: Path) -> Path:
        return paths.project_config_path(project_dir)

    def project_config_user_path(self, project_dir: Path) -> Path:
        return paths.project_config_user_path(project_dir)

    def load_project_config(self, path: Path) -> ProjectConfig | None:
        return config.load_project_config(path)

    def load_json(self, path: Path) -> dict | None:
        return config.load_json(path)

    def ensure_project_dirs(self, project_dir: Path) -> None:
        project.ensure_project_dirs(project_dir)

    def resolve_upgrade_policy(self, value: object | None) -> str:
        return config.resolve_upgrade_policy(value)

    def sync_project_skills(
        self,
        project_dir: Path,
        *,
        upgrade_policy: str,
        yes: bool,
        interactive: bool,
        prompt_update: Callable[[str], bool],
    ) -> skills.ProjectSkillsSyncResult:
        return skills.sync_project_skills(
            project_dir,
            upgrade_policy=upgrade_policy,
            yes=yes,
            interactive=interactive,
            prompt_update=prompt_update,
        )

    def write_project_config(self, path: Path, payload: ProjectConfig) -> None:
        config.write_project_config(path, payload)

    def ensure_project_scaffold(self, project_dir: Path) -> None:
        project.ensure_project_scaffold(project_dir)


class _BeadsGateway:
    def resolve_beads_root(self, project_dir: Path, repo_root: Path) -> Path:
        return config.resolve_beads_root(project_dir, repo_root)

    def ensure_atelier_store(self, *, beads_root: Path, cwd: Path) -> bool:
        return beads.ensure_atelier_store(beads_root=beads_root, cwd=cwd)

    def ensure_atelier_issue_prefix(self, *, beads_root: Path, cwd: Path) -> bool:
        return beads.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=cwd)

    def run_bd_command(self, args: list[str], *, beads_root: Path, cwd: Path) -> object:
        return beads.run_bd_command(args, beads_root=beads_root, cwd=cwd)

    def ensure_atelier_types(self, *, beads_root: Path, cwd: Path) -> bool:
        return beads.ensure_atelier_types(beads_root=beads_root, cwd=cwd)

    def list_policy_beads(
        self, role: str, *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        return beads.list_policy_beads(role, beads_root=beads_root, cwd=cwd)

    def extract_policy_body(self, issue: dict[str, object]) -> str:
        return beads.extract_policy_body(issue)

    def update_policy_bead(self, issue_id: str, text: str, *, beads_root: Path, cwd: Path) -> None:
        beads.update_policy_bead(issue_id, text, beads_root=beads_root, cwd=cwd)

    def create_policy_bead(self, role: str, text: str, *, beads_root: Path, cwd: Path) -> object:
        return beads.create_policy_bead(role, text, beads_root=beads_root, cwd=cwd)


class _PolicyGateway:
    def build_combined_policy(self, planner_text: str, worker_text: str) -> tuple[str, bool]:
        return policy.build_combined_policy(planner_text, worker_text)

    def edit_policy_text(self, text: str, *, project_config: ProjectConfig, cwd: Path) -> str:
        return policy.edit_policy_text(text, project_config=project_config, cwd=cwd)

    def split_combined_policy(self, text: str) -> dict[str, str] | None:
        return policy.split_combined_policy(text)

    def resolve_agent_home(
        self, project_dir: Path, project_config: ProjectConfig, *, role: str
    ) -> agent_home.AgentHome:
        return agent_home.resolve_agent_home(project_dir, project_config, role=role)

    def sync_agent_home_policy(
        self,
        agent_home: agent_home.AgentHome,
        *,
        role: str,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        policy.sync_agent_home_policy(agent_home, role=role, beads_root=beads_root, cwd=cwd)


def _build_init_service() -> InitializeProjectService:
    """Build init orchestration service with command-scoped dependencies.

    Returns:
        ``InitializeProjectService`` configured with command dependencies.
    """

    return InitializeProjectService(
        InitializeProjectDependencies(
            project=_ProjectGateway(),
            beads=_BeadsGateway(),
            policy=_PolicyGateway(),
            compose_config_service=ComposeProjectConfigService(
                build_config=config.build_project_config
            ),
            resolve_provider_service=ResolveExternalProviderService(
                resolve_provider=external_registry.resolve_planner_provider,
                choose_provider=select,
                confirm_choice=confirm,
            ),
            confirm_choice=confirm,
        )
    )


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as
            ``branch_prefix``, ``branch_pr_mode``, ``branch_history``,
            ``branch_pr_strategy``, ``agent``, ``editor_edit``, and
            ``editor_work``.

    Returns:
        None.

    Example:
        $ atelier init
    """
    service = _build_init_service()
    result = service.run(
        InitializeProjectRequest(
            args=args,
            cwd=Path.cwd(),
            stdin_isatty=sys.stdin.isatty(),
            stdout_isatty=sys.stdout.isatty(),
        )
    )
    if isinstance(result, ServiceFailure):
        hint = f"\nHint: {result.recovery_hint}" if result.recovery_hint else ""
        die(f"init failed ({result.code}): {result.message}{hint}")
    for message in result.outcome.messages:
        say(message)
