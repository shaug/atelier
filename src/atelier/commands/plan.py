"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from .. import agent_home, beads, config
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

    if bool(getattr(args, "create_epic", False)):
        beads.run_bd_command(
            ["create-form", "--type", "epic", "--label", "at:epic"],
            beads_root=beads_root,
            cwd=repo_root,
        )
        return

    epic_id = getattr(args, "epic_id", None)
    if not epic_id:
        epic_id = _create_epic(beads_root=beads_root, repo_root=repo_root)
    if not epic_id:
        die("epic id is required to continue planning")

    if confirm("Add tasks under this epic?", default=True):
        _create_tasks(epic_id, beads_root=beads_root, repo_root=repo_root)
    if confirm("Add changesets under this epic?", default=True):
        _create_changesets(epic_id, beads_root=beads_root, repo_root=repo_root)


def _create_epic(*, beads_root: Path, repo_root: Path) -> str:
    title = prompt("Epic title", required=True)
    acceptance = prompt("Acceptance criteria", required=True)
    scope = prompt("Scope (optional)", allow_empty=True)
    changeset_strategy = prompt("Changeset strategy (optional)", allow_empty=True)
    design = prompt("Design notes/link (optional)", allow_empty=True)

    description_lines = []
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
        beads.run_bd_command(
            [
                "create",
                "--parent",
                epic_id,
                "--type",
                "task",
                "--label",
                "at:changeset",
                "--title",
                title,
                "--acceptance",
                acceptance,
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
