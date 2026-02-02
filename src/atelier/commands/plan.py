"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from .. import agent_home, beads, config, policy
from .. import root_branch as root_branch_util
from ..io import confirm, die, prompt, say
from .resolve import resolve_current_project_with_repo_root


def run_planner(args: object) -> None:
    """Start a planning session for Beads epics and changesets."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    agent = agent_home.resolve_agent_home(
        project_data_dir, project_config, role="planner"
    )

    say("Beads planning session")
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    beads.ensure_agent_bead(
        agent.agent_id, beads_root=beads_root, cwd=repo_root, role="planner"
    )
    policy.sync_agent_home_policy(
        agent, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
    )

    if bool(getattr(args, "create_epic", False)):
        beads.run_bd_command(
            ["create-form", "--type", "epic", "--label", "at:epic"],
            beads_root=beads_root,
            cwd=repo_root,
        )
        return

    epic_id = getattr(args, "epic_id", None)
    if not epic_id:
        epic_id = _create_epic(
            beads_root=beads_root,
            repo_root=repo_root,
            branch_prefix=project_config.branch.prefix,
        )
    if not epic_id:
        die("epic id is required to continue planning")

    epic = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not epic:
        die(f"epic not found: {epic_id}")
    epic_issue = epic[0]
    root_branch = beads.extract_workspace_root_branch(epic_issue)
    if not root_branch:
        root_branch_value = root_branch_util.prompt_root_branch(
            title=str(epic_issue.get("title") or epic_id),
            branch_prefix=project_config.branch.prefix,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        beads.update_workspace_root_branch(
            epic_id, root_branch_value, beads_root=beads_root, cwd=repo_root
        )

    if confirm("Add tasks under this epic?", default=True):
        _create_tasks(epic_id, beads_root=beads_root, repo_root=repo_root)
    if confirm("Add changesets under this epic?", default=True):
        _create_changesets(epic_id, beads_root=beads_root, repo_root=repo_root)


def _create_epic(*, beads_root: Path, repo_root: Path, branch_prefix: str) -> str:
    title = prompt("Epic title", required=True)
    root_branch_value = root_branch_util.prompt_root_branch(
        title=title,
        branch_prefix=branch_prefix,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    acceptance = prompt("Acceptance criteria", required=True)
    scope = prompt("Scope (optional)", allow_empty=True)
    changeset_strategy = prompt("Changeset strategy (optional)", allow_empty=True)
    design = prompt("Design notes/link (optional)", allow_empty=True)

    description_lines = []
    description_lines.append(f"workspace.root_branch: {root_branch_value}")
    if scope:
        description_lines.append(f"scope: {scope}")
    if changeset_strategy:
        description_lines.append(f"changeset_strategy: {changeset_strategy}")
    description = "\n".join(description_lines).rstrip("\n")
    if description:
        description += "\n"

    args = [
        "create",
        "--type",
        "epic",
        "--label",
        "at:epic",
        "--label",
        beads.workspace_label(root_branch_value),
        "--title",
        title,
        "--acceptance",
        acceptance,
    ]
    if design:
        args.extend(["--design", design])

    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = handle.name

    try:
        result = beads.run_bd_command(
            [*args, "--body-file", temp_path, "--silent"],
            beads_root=beads_root,
            cwd=repo_root,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)

    epic_id = result.stdout.strip() if result.stdout else ""
    if not epic_id:
        die("failed to create epic bead")
    return epic_id


def _create_tasks(epic_id: str, *, beads_root: Path, repo_root: Path) -> None:
    while True:
        title = prompt("Task title (blank to finish)", allow_empty=True)
        if not title:
            return
        acceptance = prompt("Task acceptance", required=True)
        result = beads.run_bd_command(
            [
                "create",
                "--parent",
                epic_id,
                "--type",
                "task",
                "--label",
                "at:task",
                "--title",
                title,
                "--acceptance",
                acceptance,
                "--silent",
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
        task_id = result.stdout.strip() if result.stdout else ""
        if not task_id:
            die("failed to create task bead")
        if confirm("Add subtasks for this task?", default=False):
            _create_subtasks(
                parent_id=task_id, beads_root=beads_root, repo_root=repo_root
            )


def _create_subtasks(parent_id: str, *, beads_root: Path, repo_root: Path) -> None:
    while True:
        title = prompt("Subtask title (blank to finish)", allow_empty=True)
        if not title:
            return
        acceptance = prompt("Subtask acceptance", required=True)
        beads.run_bd_command(
            [
                "create",
                "--parent",
                parent_id,
                "--type",
                "task",
                "--label",
                "at:subtask",
                "--title",
                title,
                "--acceptance",
                acceptance,
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )


def _create_changesets(epic_id: str, *, beads_root: Path, repo_root: Path) -> None:
    while True:
        title = prompt("Changeset title (blank to finish)", allow_empty=True)
        if not title:
            return
        acceptance = prompt("Changeset acceptance", required=True)
        ready = confirm("Mark this changeset ready to work?", default=True)
        status_label = "cs:ready" if ready else "cs:planned"
        beads.run_bd_command(
            [
                "create",
                "--parent",
                epic_id,
                "--type",
                "task",
                "--label",
                "at:changeset",
                "--label",
                status_label,
                "--title",
                title,
                "--acceptance",
                acceptance,
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
