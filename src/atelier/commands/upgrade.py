"""Implementation for the ``atelier upgrade`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import config, git, paths, templates, workspace
from ..io import die, link_or_copy, say, warn


@dataclass
class PlanAction:
    description: str
    apply: Callable[[], None]


@dataclass
class PlanSkip:
    description: str
    reason: str


@dataclass
class UpgradePlan:
    actions: list[PlanAction]
    skips: list[PlanSkip]


@dataclass
class ProjectTarget:
    root: Path
    config: config.ProjectConfig
    enlistment: str | None


@dataclass
class WorkspaceTarget:
    project: ProjectTarget
    root: Path
    config: config.WorkspaceConfig


def confirm(prompt_text: str) -> bool:
    response = input(f"{prompt_text} [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def project_label(target: ProjectTarget) -> str:
    origin = target.config.project.origin or ""
    if origin:
        return f"{origin} ({target.root.name})"
    return target.root.name


def workspace_label(target: WorkspaceTarget) -> str:
    return target.config.workspace.branch


def hash_text(text: str) -> str:
    return config.hash_text(text)


def file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resolve_current_project() -> ProjectTarget | None:
    cwd = Path.cwd()
    repo_root = git.git_repo_root(cwd)
    if not repo_root:
        return None
    enlistment_path = git.resolve_enlistment_path(repo_root)
    origin_raw = git.git_origin_url(repo_root)
    origin = git.normalize_origin_url(origin_raw) if origin_raw else None
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        return None
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return ProjectTarget(
        root=project_root, config=config_payload, enlistment=enlistment_path
    )


def collect_all_projects() -> list[ProjectTarget]:
    root = paths.projects_root()
    if not root.exists():
        return []
    targets: list[ProjectTarget] = []
    for project_root in sorted(root.iterdir()):
        if not project_root.is_dir():
            continue
        config_path = paths.project_config_path(project_root)
        config_payload = config.load_project_config(config_path)
        if not config_payload:
            warn(f"project config missing at {config_path}")
            continue
        targets.append(
            ProjectTarget(
                root=project_root,
                config=config_payload,
                enlistment=config_payload.project.enlistment,
            )
        )
    return targets


def resolve_requested_workspaces(
    project: ProjectTarget, names: list[str]
) -> list[WorkspaceTarget]:
    resolved: list[WorkspaceTarget] = []
    seen: set[str] = set()
    branch_prefix = project.config.branch.prefix
    enlistment = project.enlistment or project.config.project.enlistment
    if not enlistment:
        die("project enlistment is required to resolve workspaces")

    for raw_name in names:
        normalized = workspace.normalize_workspace_name(raw_name)
        if not normalized:
            continue
        found = workspace.find_workspace_for_branch(
            project.root, enlistment, normalized
        )
        if not found and branch_prefix and not normalized.startswith(branch_prefix):
            candidate = f"{branch_prefix}{normalized}"
            found = workspace.find_workspace_for_branch(
                project.root, enlistment, candidate
            )
        if not found:
            warn(f"workspace not found: {normalized}")
            continue
        workspace_root, workspace_config = found
        branch = workspace_config.workspace.branch
        if branch in seen:
            continue
        resolved.append(
            WorkspaceTarget(
                project=project,
                root=workspace_root,
                config=workspace_config,
            )
        )
        seen.add(branch)
    return resolved


def collect_project_workspaces(project: ProjectTarget) -> list[WorkspaceTarget]:
    items = workspace.collect_workspaces(
        project.root, project.config, with_status=False
    )
    targets: list[WorkspaceTarget] = []
    for item in items:
        workspace_root = item["path"]
        workspace_config = config.load_workspace_config(
            paths.workspace_config_path(workspace_root)
        )
        if not workspace_config:
            warn(f"failed to load workspace config at {workspace_root}")
            continue
        targets.append(
            WorkspaceTarget(
                project=project, root=workspace_root, config=workspace_config
            )
        )
    return targets


def plan_agents_file(
    plan: UpgradePlan,
    *,
    description: str,
    file_path: Path,
    canonical_text: str,
    stored_hash: str | None,
    update_hash: Callable[[str], None] | None,
    create: Callable[[], None] | None = None,
    write_text: Callable[[str], None] | None = None,
    replacement_text: str | None = None,
) -> None:
    replacement = replacement_text if replacement_text is not None else canonical_text
    if not file_path.exists():
        if create is None and write_text is None:
            return

        def apply_create() -> None:
            if create is not None:
                create()
            elif write_text is not None:
                write_text(replacement)
            if update_hash is not None:
                update_hash(hash_text(replacement))

        plan.actions.append(PlanAction(description=description, apply=apply_create))
        return

    current_text = file_text(file_path)
    current_hash = hash_text(current_text)
    if stored_hash is not None:
        unmodified = current_hash == stored_hash
    else:
        unmodified = current_text == canonical_text

    if not unmodified:
        plan.skips.append(PlanSkip(description=description, reason="modified"))
        return

    if current_text != canonical_text:

        def apply_update() -> None:
            if write_text is not None:
                write_text(replacement)
            else:
                file_path.write_text(replacement, encoding="utf-8")
            if update_hash is not None:
                update_hash(hash_text(replacement))

        plan.actions.append(PlanAction(description=description, apply=apply_update))
        return

    if update_hash is not None and stored_hash != current_hash:

        def apply_record() -> None:
            if update_hash is not None:
                update_hash(current_hash)

        plan.actions.append(PlanAction(description=description, apply=apply_record))


def plan_project_agents(
    plan: UpgradePlan,
    project: ProjectTarget,
) -> None:
    canonical = templates.project_agents_template()
    managed = project.config.atelier.managed_files
    project_label_text = project_label(project)

    template_agents_path = project.root / paths.TEMPLATES_DIRNAME / "AGENTS.md"
    template_key = f"{paths.TEMPLATES_DIRNAME}/AGENTS.md"
    template_unmodified = True
    if template_agents_path.exists():
        template_text = file_text(template_agents_path)
        template_hash = hash_text(template_text)
        stored_template_hash = managed.get(template_key)
        if stored_template_hash is not None:
            template_unmodified = template_hash == stored_template_hash
        else:
            template_unmodified = template_text == canonical

    def update_template_hash(value: str) -> None:
        config.update_project_managed_files(project.root, {template_key: value})

    plan_agents_file(
        plan,
        description=f"Project template AGENTS.md ({project_label_text})",
        file_path=template_agents_path,
        canonical_text=canonical,
        stored_hash=managed.get(template_key),
        update_hash=update_template_hash,
        write_text=lambda text: template_agents_path.write_text(text, encoding="utf-8"),
    )

    agents_path = project.root / "AGENTS.md"
    agents_key = "AGENTS.md"

    def update_agents_hash(value: str) -> None:
        config.update_project_managed_files(project.root, {agents_key: value})

    record_root_hash = template_unmodified
    agents_hash_updater = update_agents_hash if record_root_hash else None

    def create_agents() -> None:
        if template_agents_path.exists():
            link_or_copy(template_agents_path, agents_path)
        else:
            agents_path.write_text(canonical, encoding="utf-8")

    plan_agents_file(
        plan,
        description=f"Project AGENTS.md ({project_label_text})",
        file_path=agents_path,
        canonical_text=canonical,
        stored_hash=managed.get(agents_key),
        update_hash=agents_hash_updater,
        create=create_agents,
        write_text=lambda text: agents_path.write_text(text, encoding="utf-8"),
    )


def plan_workspace_agents(plan: UpgradePlan, target: WorkspaceTarget) -> None:
    canonical = templates.workspace_agents_template()
    managed = target.config.atelier.managed_files
    workspace_label_text = workspace_label(target)
    project_template_path = target.project.root / paths.TEMPLATES_DIRNAME / "AGENTS.md"
    if project_template_path.exists():
        source_text = file_text(project_template_path)
    else:
        source_text = canonical

    agents_path = target.root / "AGENTS.md"
    agents_key = "AGENTS.md"

    def update_agents_hash(value: str) -> None:
        config.update_workspace_managed_files(target.root, {agents_key: value})

    record_hash = source_text == canonical
    agents_hash_updater = update_agents_hash if record_hash else None

    def create_agents() -> None:
        if project_template_path.exists():
            link_or_copy(project_template_path, agents_path)
        else:
            agents_path.write_text(source_text, encoding="utf-8")

    plan_agents_file(
        plan,
        description=f"Workspace AGENTS.md ({workspace_label_text})",
        file_path=agents_path,
        canonical_text=canonical,
        stored_hash=managed.get(agents_key),
        update_hash=agents_hash_updater,
        create=create_agents,
        write_text=lambda text: agents_path.write_text(text, encoding="utf-8"),
        replacement_text=source_text,
    )


def plan_workspace_policy_rename(plan: UpgradePlan, target: WorkspaceTarget) -> None:
    success_path = target.root / "SUCCESS.md"
    legacy_path = target.root / "WORKSPACE.md"
    if success_path.exists() or not legacy_path.exists():
        return

    def apply_rename() -> None:
        legacy_path.rename(success_path)

    plan.actions.append(
        PlanAction(
            description=f"Rename WORKSPACE.md to SUCCESS.md ({workspace_label(target)})",
            apply=apply_rename,
        )
    )


def plan_project_templates(plan: UpgradePlan, project: ProjectTarget) -> None:
    project_label_text = project_label(project)
    templates_root = project.root / paths.TEMPLATES_DIRNAME
    success_path = templates_root / "SUCCESS.md"
    if not success_path.exists():

        def apply_create_success() -> None:
            paths.ensure_dir(success_path.parent)
            success_path.write_text(templates.success_md_template(), encoding="utf-8")

        plan.actions.append(
            PlanAction(
                description=f"Create templates/SUCCESS.md ({project_label_text})",
                apply=apply_create_success,
            )
        )


def plan_project_template_refresh(plan: UpgradePlan, project: ProjectTarget) -> None:
    project_label_text = project_label(project)
    templates_root = project.root / paths.TEMPLATES_DIRNAME
    refresh_targets = [
        (
            "AGENTS.md",
            lambda: templates.project_agents_template(prefer_installed=True),
            f"{paths.TEMPLATES_DIRNAME}/AGENTS.md",
        ),
        (
            "SUCCESS.md",
            lambda: templates.success_md_template(prefer_installed=True),
            None,
        ),
    ]
    for filename, read_text, managed_key in refresh_targets:
        dest = templates_root / filename

        def apply_refresh(
            path: Path = dest,
            reader: Callable[[], str] = read_text,
            key: str | None = managed_key,
        ) -> None:
            text = reader()
            paths.ensure_dir(path.parent)
            path.write_text(text, encoding="utf-8")
            if key:
                config.update_project_managed_files(
                    project.root, {key: hash_text(text)}
                )

        plan.actions.append(
            PlanAction(
                description=(
                    f"Refresh templates/{filename} from installed cache "
                    f"({project_label_text})"
                ),
                apply=apply_refresh,
            )
        )


def summarize_plan(plan: UpgradePlan, dry_run: bool) -> None:
    header = "Upgrade plan (dry-run):" if dry_run else "Upgrade plan:"
    say(header)
    if plan.actions:
        for action in plan.actions:
            say(f"- {action.description}")
    else:
        say("- No changes to apply.")
    if plan.skips:
        say("Skipped:")
        for skip in plan.skips:
            say(f"- {skip.description} ({skip.reason})")


def upgrade(args: object) -> None:
    """Upgrade project/workspace metadata and templates safely."""
    workspace_names = list(getattr(args, "workspace_names", []) or [])
    installed = bool(getattr(args, "installed", False))
    all_projects = bool(getattr(args, "all_projects", False))
    no_projects = bool(getattr(args, "no_projects", False))
    no_workspaces = bool(getattr(args, "no_workspaces", False))
    dry_run = bool(getattr(args, "dry_run", False))
    auto_yes = bool(getattr(args, "yes", False))

    if all_projects and no_projects:
        die("--all-projects and --no-projects cannot be combined")
    if all_projects and workspace_names:
        die("workspace arguments cannot be used with --all-projects")
    if no_workspaces and workspace_names:
        die("workspace arguments cannot be used with --no-workspaces")

    projects: list[ProjectTarget] = []
    current_project = None
    if all_projects:
        projects = collect_all_projects()
    else:
        current_project = resolve_current_project()
        if current_project is not None:
            projects = [current_project]

    if not projects and workspace_names:
        die("workspace upgrades require an Atelier project")

    if not projects and not installed:
        warn("not inside an Atelier project; nothing to upgrade")
        return

    refresh_project_templates = False
    if installed and not no_projects and projects:
        if auto_yes:
            refresh_project_templates = True
        else:
            refresh_project_templates = confirm(
                "Refresh project templates from the installed cache?"
            )

    plan = UpgradePlan(actions=[], skips=[])

    if installed:

        def apply_installed_refresh() -> None:
            templates.refresh_installed_templates()

        plan.actions.append(
            PlanAction(
                description="Refresh installed template cache",
                apply=apply_installed_refresh,
            )
        )

    if projects and not no_projects:
        for project in projects:
            plan_project_templates(plan, project)
            plan_project_agents(plan, project)
            if refresh_project_templates:
                plan_project_template_refresh(plan, project)

    if projects and not no_workspaces:
        workspace_targets: list[WorkspaceTarget] = []
        if workspace_names:
            if current_project is None:
                die("workspace upgrades require the current Atelier project")
            workspace_targets = resolve_requested_workspaces(
                current_project, workspace_names
            )
        else:
            for project in projects:
                workspace_targets.extend(collect_project_workspaces(project))

        for target in workspace_targets:
            plan_workspace_policy_rename(plan, target)
            plan_workspace_agents(plan, target)

    summarize_plan(plan, dry_run=dry_run)
    if not plan.actions:
        return

    if dry_run:
        return

    if not auto_yes and not confirm("Apply these changes?"):
        say("Upgrade cancelled.")
        return

    for action in plan.actions:
        action.apply()

    say("Upgrade complete.")
