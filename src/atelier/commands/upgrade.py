"""Implementation for the ``atelier upgrade`` command.

Applies managed template updates according to the configured upgrade policy.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import __version__, config, git, paths, templates, workspace
from ..io import confirm, die, link_or_copy, say, select, warn


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


def backup_json(path: Path) -> None:
    backup_path = path.with_suffix(".json.bak")
    if backup_path.exists():
        return
    shutil.move(path, backup_path)


def project_label_from_parts(root: Path, origin: str | None) -> str:
    if origin:
        return f"{origin} ({root.name})"
    return root.name


def split_project_payload(payload: dict) -> tuple[dict, dict]:
    user_payload: dict = {}
    for key in ("branch", "agent", "editor", "git"):
        if key in payload:
            user_payload[key] = payload.get(key)
    project_payload = payload.get("project")
    if isinstance(project_payload, dict):
        project_user: dict = {}
        for key in ("provider", "provider_url", "owner"):
            if key in project_payload:
                project_user[key] = project_payload.get(key)
        if project_user:
            user_payload["project"] = project_user
    atelier_payload = dict(payload.get("atelier", {}) or {})
    upgrade = atelier_payload.pop("upgrade", None)
    if "atelier" in payload and "upgrade" in payload.get("atelier", {}):
        user_payload["atelier"] = {"upgrade": upgrade}
    system_payload = dict(payload)
    for key in ("branch", "agent", "editor", "git"):
        system_payload.pop(key, None)
    project_system = dict(system_payload.get("project", {}) or {})
    for key in ("provider", "provider_url", "owner"):
        project_system.pop(key, None)
    if "project" in system_payload:
        system_payload["project"] = project_system
    system_payload["atelier"] = atelier_payload
    return system_payload, user_payload


def load_project_user_config_for_upgrade(
    path: Path, *, plan: UpgradePlan | None, label: str
) -> config.ProjectUserConfig | None:
    payload = config.load_json(path)
    if not payload:
        return None
    migrated_payload, changed = config.migrate_legacy_editor_payload(payload)
    if changed and plan is not None:

        def apply_migration() -> None:
            backup_json(path)
            config.write_json(path, migrated_payload)

        plan.actions.append(
            PlanAction(
                description=f"Migrate legacy editor config ({label})",
                apply=apply_migration,
            )
        )
    return config.parse_project_user_config(migrated_payload, path)


def load_project_target_for_upgrade(
    project_root: Path, *, plan: UpgradePlan | None
) -> ProjectTarget | None:
    sys_path = paths.project_config_sys_path(project_root)
    user_path = paths.project_config_user_path(project_root)
    legacy_path = paths.project_config_legacy_path(project_root)

    if not sys_path.exists() and not user_path.exists() and legacy_path.exists():
        payload = config.load_json(legacy_path)
        if not payload:
            return None
        system_payload, user_payload = split_project_payload(payload)
        user_payload, _ = config.migrate_legacy_editor_payload(user_payload)
        system_config = config.parse_project_system_config(system_payload, legacy_path)
        user_config = config.parse_project_user_config(user_payload, legacy_path)
        merged = config.merge_project_configs(system_config, user_config)
        config.ensure_agent_available(merged.agent.default, label="project")
        target = ProjectTarget(
            root=project_root,
            config=merged,
            enlistment=merged.project.enlistment,
        )
        if plan is not None:
            label = project_label(target)

            def apply_migration() -> None:
                backup_json(legacy_path)
                config.write_project_system_config(sys_path, system_config)
                config.write_project_user_config(user_path, user_config)

            description = f"Migrate legacy project config.json ({label})"
            plan.actions.append(
                PlanAction(description=description, apply=apply_migration)
            )
        return target

    system_config = config.load_project_system_config(sys_path)
    if not system_config:
        return None
    label = project_label_from_parts(project_root, system_config.project.origin)
    user_config = load_project_user_config_for_upgrade(
        user_path, plan=plan, label=label
    )
    merged = config.merge_project_configs(system_config, user_config)
    config.ensure_agent_available(merged.agent.default, label="project")
    return ProjectTarget(
        root=project_root,
        config=merged,
        enlistment=merged.project.enlistment,
    )


def plan_installed_defaults_migration(plan: UpgradePlan) -> None:
    defaults_path = paths.installed_config_path()
    payload = config.load_json(defaults_path)
    if not payload:
        return
    migrated_payload, changed = config.migrate_legacy_editor_payload(payload)
    if not changed:
        return
    config.parse_project_user_config(migrated_payload, defaults_path)

    def apply_migration() -> None:
        backup_json(defaults_path)
        config.write_json(defaults_path, migrated_payload)

    plan.actions.append(
        PlanAction(
            description="Migrate legacy editor config (installed defaults)",
            apply=apply_migration,
        )
    )


def resolve_current_project(plan: UpgradePlan | None) -> ProjectTarget | None:
    cwd = Path.cwd()
    repo_root = git.git_repo_root(cwd)
    if not repo_root:
        return None
    enlistment_path = git.resolve_enlistment_path(repo_root)
    origin_raw = git.git_origin_url(repo_root)
    origin = git.normalize_origin_url(origin_raw) if origin_raw else None
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    target = load_project_target_for_upgrade(project_root, plan=plan)
    if not target:
        return None
    project_enlistment = target.config.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return ProjectTarget(
        root=target.root,
        config=target.config,
        enlistment=enlistment_path,
    )


def collect_all_projects(plan: UpgradePlan | None) -> list[ProjectTarget]:
    root = paths.projects_root()
    if not root.exists():
        return []
    targets: list[ProjectTarget] = []
    for project_root in sorted(root.iterdir()):
        if not project_root.is_dir():
            continue
        config_path = paths.project_config_path(project_root)
        target = load_project_target_for_upgrade(project_root, plan=plan)
        if not target:
            warn(f"project config missing at {config_path}")
            continue
        targets.append(target)
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
        resolved_branch = normalized
        found = workspace.find_workspace_for_branch(
            project.root,
            enlistment,
            normalized,
            allow_missing_config=True,
        )
        if not found and branch_prefix and not normalized.startswith(branch_prefix):
            candidate = f"{branch_prefix}{normalized}"
            found = workspace.find_workspace_for_branch(
                project.root,
                enlistment,
                candidate,
                allow_missing_config=True,
            )
            if found:
                resolved_branch = candidate
        if not found:
            warn(f"workspace not found: {normalized}")
            continue
        workspace_root, workspace_config = found
        branch = (
            workspace_config.workspace.branch if workspace_config else resolved_branch
        )
        if workspace_config is None:
            workspace_config = build_workspace_config(project, branch)
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


def build_workspace_config(
    project: ProjectTarget, branch: str
) -> config.WorkspaceConfig:
    enlistment = project.enlistment or project.config.project.enlistment
    if not enlistment:
        die("project enlistment is required to repair workspaces")
    workspace_id = workspace.workspace_identifier(enlistment, branch)
    upgrade_policy = config.resolve_upgrade_policy(project.config.atelier.upgrade)
    return config.WorkspaceConfig(
        workspace={
            "branch": branch,
            "branch_pr": project.config.branch.pr,
            "branch_history": project.config.branch.history,
            "id": workspace_id,
        },
        atelier={
            "version": __version__,
            "created_at": config.utc_now(),
            "upgrade": upgrade_policy,
        },
    )


def _strip_workspace_dir_hash(name: str) -> str:
    parts = name.rsplit("-", 1)
    if len(parts) == 2:
        suffix = parts[1].lower()
        if len(suffix) == 8 and all(char in "0123456789abcdef" for char in suffix):
            base = parts[0]
            if base:
                return base
    return name


def _guess_branch_from_dirname(name: str, branch_prefix: str | None) -> str:
    base = _strip_workspace_dir_hash(name)
    if branch_prefix:
        prefix_base = branch_prefix.rstrip("/")
        if prefix_base and base.startswith(f"{prefix_base}-"):
            remainder = base[len(prefix_base) + 1 :]
            if remainder:
                return f"{branch_prefix}{remainder}"
    return base


def guess_workspace_branch(project: ProjectTarget, workspace_dir: Path) -> str:
    repo_dir = workspace_dir / "repo"
    git_path = config.resolve_git_path(project.config)
    if repo_dir.exists() and git.git_is_repo(repo_dir, git_path=git_path):
        branch = git.git_current_branch(repo_dir, git_path=git_path)
        if branch and branch != "HEAD":
            return branch
    return _guess_branch_from_dirname(workspace_dir.name, project.config.branch.prefix)


def plan_workspace_config_repair(plan: UpgradePlan, target: WorkspaceTarget) -> None:
    sys_path = paths.workspace_config_sys_path(target.root)
    user_path = paths.workspace_config_user_path(target.root)
    if sys_path.exists() and user_path.exists():
        return

    def apply_repair() -> None:
        if not sys_path.exists():
            system_config = config.WorkspaceSystemConfig(
                workspace=target.config.workspace.model_dump(),
                atelier={
                    "version": __version__,
                    "created_at": config.utc_now(),
                    "managed_files": dict(target.config.atelier.managed_files),
                },
            )
            config.write_workspace_system_config(sys_path, system_config)
        if not user_path.exists():
            upgrade_value = target.config.atelier.upgrade
            if upgrade_value is None:
                upgrade_value = config.resolve_upgrade_policy(
                    target.project.config.atelier.upgrade
                )
            user_config = config.WorkspaceUserConfig(atelier={"upgrade": upgrade_value})
            config.write_workspace_user_config(user_path, user_config)

    plan.actions.append(
        PlanAction(
            description=f"Repair workspace config ({workspace_label(target)})",
            apply=apply_repair,
        )
    )


def collect_project_workspaces(project: ProjectTarget) -> list[WorkspaceTarget]:
    targets: list[WorkspaceTarget] = []
    workspaces_root = project.root / paths.WORKSPACES_DIRNAME
    if not workspaces_root.exists():
        return targets
    for workspace_root in sorted(workspaces_root.iterdir()):
        if not workspace_root.is_dir():
            continue
        config_path = paths.workspace_config_path(workspace_root)
        if not config_path.exists():
            continue
        workspace_config = config.load_workspace_config(config_path)
        if not workspace_config:
            warn(f"failed to load workspace config at {workspace_root}")
            continue
        targets.append(
            WorkspaceTarget(
                project=project, root=workspace_root, config=workspace_config
            )
        )
    return targets


def collect_orphaned_workspaces(project: ProjectTarget) -> list[Path]:
    workspaces_root = project.root / paths.WORKSPACES_DIRNAME
    if not workspaces_root.exists():
        return []
    orphaned: list[Path] = []
    for workspace_root in sorted(workspaces_root.iterdir()):
        if not workspace_root.is_dir():
            continue
        config_path = paths.workspace_config_sys_path(workspace_root)
        if not config_path.exists():
            orphaned.append(workspace_root)
    return orphaned


def plan_orphaned_workspaces(
    plan: UpgradePlan,
    project: ProjectTarget,
    orphaned: list[Path],
    *,
    auto_yes: bool,
) -> list[WorkspaceTarget]:
    targets: list[WorkspaceTarget] = []
    for workspace_root in orphaned:
        branch_guess = guess_workspace_branch(project, workspace_root)
        if not branch_guess:
            branch_guess = workspace_root.name
        label = project_label(project)
        prompt = (
            "Workspace config missing for "
            f"{workspace_root.name} ({label}); "
            f"repair using branch '{branch_guess}' or remove it?"
        )
        if auto_yes:
            choice = "repair"
        else:
            choice = select(prompt, ["repair", "remove", "skip"], default="repair")
        if choice == "repair":
            targets.append(
                WorkspaceTarget(
                    project=project,
                    root=workspace_root,
                    config=build_workspace_config(project, branch_guess),
                )
            )
            continue
        if choice == "remove":

            def apply_remove(path: Path = workspace_root) -> None:
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    warn(f"failed to remove orphaned workspace at {path}: {exc}")

            plan.actions.append(
                PlanAction(
                    description=(
                        "Remove orphaned workspace directory "
                        f"{workspace_root.name} ({label})"
                    ),
                    apply=apply_remove,
                )
            )
            continue
        plan.skips.append(
            PlanSkip(
                description=(
                    f"Skip orphaned workspace directory {workspace_root.name} ({label})"
                ),
                reason="skipped",
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
    canonical = templates.agents_template()
    managed = project.config.atelier.managed_files
    project_label_text = project_label(project)

    template_agents_path = project.root / paths.TEMPLATES_DIRNAME / "AGENTS.md"
    template_key = f"{paths.TEMPLATES_DIRNAME}/AGENTS.md"

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

    legacy_agents_path = project.root / "AGENTS.md"
    if legacy_agents_path.exists() or legacy_agents_path.is_symlink():
        remove_description = f"Remove legacy project AGENTS.md ({project_label_text})"
        is_template_link = False
        if legacy_agents_path.is_symlink():
            try:
                is_template_link = (
                    legacy_agents_path.resolve() == template_agents_path.resolve()
                )
            except FileNotFoundError:
                is_template_link = False
        if is_template_link:
            plan.actions.append(
                PlanAction(
                    description=remove_description,
                    apply=legacy_agents_path.unlink,
                )
            )
        elif legacy_agents_path.is_file():
            legacy_text = file_text(legacy_agents_path)
            if legacy_text == canonical:
                plan.actions.append(
                    PlanAction(
                        description=remove_description,
                        apply=legacy_agents_path.unlink,
                    )
                )
            else:
                plan.skips.append(
                    PlanSkip(
                        description=remove_description,
                        reason="modified",
                    )
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


def plan_workspace_persist(plan: UpgradePlan, target: WorkspaceTarget) -> None:
    workspace_label_text = workspace_label(target)
    branch_pr = target.config.workspace.branch_pr
    branch_history = target.config.workspace.branch_history
    if branch_pr is None or branch_history is None:
        plan.skips.append(
            PlanSkip(
                description=f"Workspace PERSIST.md ({workspace_label_text})",
                reason="missing branch settings",
            )
        )
        return
    canonical = templates.render_persist(branch_pr, branch_history)
    managed = target.config.atelier.managed_files
    persist_path = target.root / "PERSIST.md"
    persist_key = "PERSIST.md"

    def update_persist_hash(value: str) -> None:
        config.update_workspace_managed_files(target.root, {persist_key: value})

    plan_agents_file(
        plan,
        description=f"Workspace PERSIST.md ({workspace_label_text})",
        file_path=persist_path,
        canonical_text=canonical,
        stored_hash=managed.get(persist_key),
        update_hash=update_persist_hash,
        write_text=lambda text: persist_path.write_text(text, encoding="utf-8"),
    )


def plan_project_templates(plan: UpgradePlan, project: ProjectTarget) -> None:
    project_label_text = project_label(project)
    templates_root = project.root / paths.TEMPLATES_DIRNAME
    success_path = templates_root / "SUCCESS.md"
    if not success_path.exists():

        def apply_create_success() -> None:
            paths.ensure_dir(success_path.parent)
            success_text = templates.success_md_template(prefer_installed=True)
            success_path.write_text(success_text, encoding="utf-8")
            config.update_project_managed_files(
                project.root,
                {f"{paths.TEMPLATES_DIRNAME}/SUCCESS.md": hash_text(success_text)},
            )

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
            lambda: templates.agents_template(prefer_installed=True),
            f"{paths.TEMPLATES_DIRNAME}/AGENTS.md",
        ),
        (
            "SUCCESS.md",
            lambda: templates.success_md_template(prefer_installed=True),
            f"{paths.TEMPLATES_DIRNAME}/SUCCESS.md",
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

    plan = UpgradePlan(actions=[], skips=[])

    projects: list[ProjectTarget] = []
    current_project = None
    if all_projects:
        projects = collect_all_projects(plan)
    else:
        current_project = resolve_current_project(plan)
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

    if installed:
        plan_installed_defaults_migration(plan)

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

    workspace_targets: list[WorkspaceTarget] = []
    if projects and not no_workspaces:
        if workspace_names:
            if current_project is None:
                die("workspace upgrades require the current Atelier project")
            workspace_targets = resolve_requested_workspaces(
                current_project, workspace_names
            )
        else:
            for project in projects:
                workspace_targets.extend(collect_project_workspaces(project))
                orphaned = collect_orphaned_workspaces(project)
                if orphaned:
                    workspace_targets.extend(
                        plan_orphaned_workspaces(
                            plan, project, orphaned, auto_yes=auto_yes
                        )
                    )

        for target in workspace_targets:
            plan_workspace_config_repair(plan, target)
            plan_workspace_agents(plan, target)
            plan_workspace_persist(plan, target)

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

    if projects and not no_projects:
        for project in projects:
            config_path = paths.project_config_sys_path(project.root)
            project_config = config.load_project_system_config(config_path)
            if not project_config:
                continue
            atelier_section = project_config.atelier.model_copy(
                update={"version": __version__}
            )
            project_config = project_config.model_copy(
                update={"atelier": atelier_section}
            )
            config.write_project_system_config(config_path, project_config)

    if workspace_targets:
        for target in workspace_targets:
            config_path = paths.workspace_config_sys_path(target.root)
            workspace_config = config.load_workspace_system_config(config_path)
            if not workspace_config:
                continue
            atelier_section = workspace_config.atelier.model_copy(
                update={"version": __version__}
            )
            workspace_config = workspace_config.model_copy(
                update={"atelier": atelier_section}
            )
            config.write_workspace_system_config(config_path, workspace_config)

    say("Upgrade complete.")
