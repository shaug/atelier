"""Command-line interface entrypoint for Atelier.

Defines the Typer app, global options, and subcommands that delegate to the
implementation modules under ``atelier.commands``.

Example:
    $ atelier --help
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import click
import typer

try:
    from click.shell_completion import split_arg_string
except ImportError:  # pragma: no cover - legacy Click fallback
    from click.parser import split_arg_string

from . import __version__, beads, config, git, paths
from .commands import clean as clean_cmd
from .commands import config as config_cmd
from .commands import describe as describe_cmd
from .commands import edit as edit_cmd
from .commands import gc as gc_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import new as new_cmd
from .commands import plan as plan_cmd
from .commands import policy as policy_cmd
from .commands import shell as shell_cmd
from .commands import work as work_cmd
from .exec import try_run_command
from .io import warn

app = typer.Typer(
    add_completion=True,
    help=(
        "Workspace-first CLI for managing isolated, agent-assisted work. "
        "Use 'atelier init' to register a repo, then 'atelier work' to start "
        "a worker session against the next ready changeset."
    ),
)
_COMPLETE_ENV = "_ATELIER_COMPLETE"
_DEFAULT_BRANCH_EXCLUDES = {"main", "master"}


def _ensure_completion_env() -> None:
    """Fill missing completion vars so Click can parse completion requests."""
    if _COMPLETE_ENV not in os.environ:
        return
    if "COMP_WORDS" in os.environ and "COMP_CWORD" in os.environ:
        return

    comp_line = os.environ.get("COMP_LINE")
    comp_point = os.environ.get("COMP_POINT")
    if comp_line is not None and comp_point is not None:
        try:
            point = int(comp_point)
        except ValueError:
            point = len(comp_line)
        line = comp_line[:point]
        words = split_arg_string(line)
        if not words:
            prog = os.path.basename(sys.argv[0]) if sys.argv else "atelier"
            line = prog
            words = [prog]
        cword = len(words) if line.endswith(" ") else max(len(words) - 1, 0)
        os.environ.setdefault("COMP_WORDS", line)
        os.environ.setdefault("COMP_CWORD", str(cword))
        return

    prog = os.path.basename(sys.argv[0]) if sys.argv else "atelier"
    os.environ.setdefault("COMP_WORDS", prog)
    os.environ.setdefault("COMP_CWORD", "0")


def _resolve_completion_project(
    cwd: Path | None = None,
) -> tuple[Path, Path, config.ProjectConfig, str | None] | None:
    try:
        repo_root, enlistment_path, _, origin = git.resolve_repo_enlistment(
            cwd or Path.cwd()
        )
    except SystemExit:
        return None
    except Exception:
        return None
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        return None
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        return None
    git_path = config.resolve_git_path(config_payload)
    return repo_root, project_root, config_payload, git_path


def _collect_workspace_root_branches(repo_root: Path, *, beads_root: Path) -> list[str]:
    cmd = ["bd", "list", "--label", "at:epic", "--json"]
    result = try_run_command(cmd, cwd=repo_root, env=beads.beads_env(beads_root))
    if not result or result.returncode != 0:
        return []
    raw = result.stdout.strip() if result.stdout else ""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        issues = [payload]
    elif isinstance(payload, list):
        issues = payload
    else:
        return []
    roots: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        status = str(issue.get("status") or "").lower()
        if status and status not in {"open", "in_progress", "ready"}:
            continue
        root_branch = beads.extract_workspace_root_branch(issue)
        if root_branch:
            roots.append(root_branch)
    return roots


def _filter_completion_candidates(values: list[str], incomplete: str) -> list[str]:
    filtered = [
        value
        for value in values
        if value
        and value.startswith(incomplete)
        and value not in _DEFAULT_BRANCH_EXCLUDES
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for value in filtered:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _workspace_name_shell_complete(
    _ctx: click.Context, _args: list[str], incomplete: str
) -> list[str]:
    resolved = _resolve_completion_project()
    if not resolved:
        return []
    repo_root, project_root, config_payload, _git_path = resolved
    project_data_dir = config.resolve_project_data_dir(project_root, config_payload)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    names = _collect_workspace_root_branches(repo_root, beads_root=beads_root)
    return _filter_completion_candidates(names, incomplete)


def _workspace_only_shell_complete(
    _ctx: click.Context, _args: list[str], incomplete: str
) -> list[str]:
    resolved = _resolve_completion_project()
    if not resolved:
        return []
    repo_root, project_root, config_payload, _git_path = resolved
    project_data_dir = config.resolve_project_data_dir(project_root, config_payload)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    names = _collect_workspace_root_branches(repo_root, beads_root=beads_root)
    return _filter_completion_candidates(names, incomplete)


def _version_callback(value: bool) -> None:
    """Handle the ``--version`` option and exit early.

    Args:
        value: ``True`` when ``--version`` is provided.

    Returns:
        None. Raises ``typer.Exit`` to stop execution when ``value`` is true.

    Example:
        $ atelier --version
    """
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def app_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Workspace-first CLI for managing isolated, agent-assisted work.

    Args:
        version: When true, prints the CLI version and exits.

    Returns:
        None.

    Example:
        $ atelier init
    """


@app.command(
    "init",
    help="Register the current repo as an Atelier project in the data directory.",
)
def init_command(
    branch_prefix: Annotated[
        str | None,
        typer.Option("--branch-prefix", help="prefix for workspace branches"),
    ] = None,
    branch_pr: Annotated[
        str | None,
        typer.Option(
            "--branch-pr",
            help="expect pull requests for workspace branches (true/false)",
        ),
    ] = None,
    branch_history: Annotated[
        str | None,
        typer.Option(
            "--branch-history",
            help="branch history policy (manual|squash|merge|rebase)",
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="agent name",
        ),
    ] = None,
    editor_edit: Annotated[
        str | None,
        typer.Option("--editor-edit", help="editor command for edit actions"),
    ] = None,
    editor_work: Annotated[
        str | None,
        typer.Option("--editor-work", help="editor command for work actions"),
    ] = None,
) -> None:
    """Initialize an Atelier project for the current Git repo.

    Args:
        branch_prefix: Prefix for new workspace branches (optional).
        branch_pr: Whether workspace branches expect pull requests (true/false).
        branch_history: History policy (manual|squash|merge|rebase).
        agent: Agent name.
        editor_edit: Editor command used for blocking edits (policy docs).
        editor_work: Editor command used for opening the workspace repo.
    Returns:
        None.

    Example:
        $ atelier init --branch-prefix scott/ --branch-history rebase
    """
    init_cmd.init_project(
        SimpleNamespace(
            branch_prefix=branch_prefix,
            branch_pr=branch_pr,
            branch_history=branch_history,
            agent=agent,
            editor_edit=editor_edit,
            editor_work=editor_work,
        )
    )


@app.command(
    "new",
    help="Create a new local repo, register it as a project, and open its workspace.",
)
def new_command(
    path: Annotated[
        str | None,
        typer.Argument(help="path for the new project (optional)"),
    ] = None,
    branch_prefix: Annotated[
        str | None,
        typer.Option("--branch-prefix", help="prefix for workspace branches"),
    ] = None,
    branch_pr: Annotated[
        str | None,
        typer.Option(
            "--branch-pr",
            help="expect pull requests for workspace branches (true/false)",
        ),
    ] = None,
    branch_history: Annotated[
        str | None,
        typer.Option(
            "--branch-history",
            help="branch history policy (manual|squash|merge|rebase)",
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="agent name",
        ),
    ] = None,
    editor_edit: Annotated[
        str | None,
        typer.Option("--editor-edit", help="editor command for edit actions"),
    ] = None,
    editor_work: Annotated[
        str | None,
        typer.Option("--editor-work", help="editor command for work actions"),
    ] = None,
) -> None:
    """Create a brand-new project and open the first workspace.

    Args:
        path: Path for the new project (optional).
        branch_prefix: Prefix for new workspace branches (optional).
        branch_pr: Whether workspace branches expect pull requests (true/false).
        branch_history: History policy (manual|squash|merge|rebase).
        agent: Agent name.
        editor_edit: Editor command used for blocking edits (policy docs).
        editor_work: Editor command used for opening the workspace repo.

    Returns:
        None.

    Example:
        $ atelier new ~/code/greenfield
    """
    new_cmd.new_project(
        SimpleNamespace(
            path=path,
            branch_prefix=branch_prefix,
            branch_pr=branch_pr,
            branch_history=branch_history,
            agent=agent,
            editor_edit=editor_edit,
            editor_work=editor_work,
        )
    )


@app.command(
    "open",
    help="Deprecated: use 'atelier work' instead.",
)
def open_command(
    epic_id: Annotated[
        str | None,
        typer.Argument(
            help="epic bead id to work on (optional)",
        ),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help="worker selection mode: prompt or auto (defaults to ATELIER_MODE)",
        ),
    ] = None,
) -> None:
    """Deprecated alias for ``atelier work``.

    Args:
        epic_id: Epic bead id to work on (optional).
        mode: Worker selection mode (prompt or auto).

    Returns:
        None.

    Example:
        $ atelier work
    """
    warn("`atelier open` is deprecated; use `atelier work` instead.")
    work_cmd.start_worker(SimpleNamespace(epic_id=epic_id, mode=mode))


@app.command("plan", help="Start a planner session for Beads epics.")
def plan_command(
    create_epic: Annotated[
        bool,
        typer.Option(
            "--create-epic",
            help="open an interactive bead form to create a new epic",
        ),
    ] = False,
    epic_id: Annotated[
        str | None,
        typer.Option("--epic-id", help="existing epic bead id to plan against"),
    ] = None,
) -> None:
    """Start a planner session."""
    plan_cmd.run_planner(SimpleNamespace(create_epic=create_epic, epic_id=epic_id))


@app.command(
    "work",
    help="Start a worker session for the next ready changeset.",
)
def work_command(
    epic_id: Annotated[
        str | None,
        typer.Argument(
            help="epic bead id to work on (optional)",
        ),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help="worker selection mode: prompt or auto (defaults to ATELIER_MODE)",
        ),
    ] = None,
) -> None:
    """Start a worker session."""
    work_cmd.start_worker(SimpleNamespace(epic_id=epic_id, mode=mode))


@app.command(
    "shell",
    help="Open a shell in the workspace repo (or root with --workspace).",
)
def shell_command(
    workspace_name: Annotated[
        str,
        typer.Argument(
            help="workspace branch to open",
            autocompletion=_workspace_only_shell_complete,
        ),
    ],
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="shell path or name for interactive mode"),
    ] = None,
    command: Annotated[
        list[str] | None,
        typer.Argument(
            help="command to run in the workspace repo (or root with --workspace)"
        ),
    ] = None,
    workspace_root: Annotated[
        bool,
        typer.Option("--workspace", help="open the workspace root instead of repo"),
    ] = False,
    set_title: Annotated[
        bool,
        typer.Option("--set-title", help="emit a terminal title escape"),
    ] = False,
) -> None:
    """Open a shell in the workspace repo or run a command there."""
    shell_cmd.open_workspace_shell(
        SimpleNamespace(
            workspace_name=workspace_name,
            shell=shell,
            command=command or [],
            workspace_root=workspace_root,
            set_title=set_title,
        )
    )


@app.command(
    "exec",
    help="Run a command in the workspace repo (or root with --workspace).",
)
def exec_command(
    workspace_name: Annotated[
        str,
        typer.Argument(
            help="workspace branch to open",
            autocompletion=_workspace_only_shell_complete,
        ),
    ],
    command: Annotated[
        list[str] | None,
        typer.Argument(
            help="command to run in the workspace repo (or root with --workspace)"
        ),
    ] = None,
    workspace_root: Annotated[
        bool,
        typer.Option("--workspace", help="open the workspace root instead of repo"),
    ] = False,
    set_title: Annotated[
        bool,
        typer.Option("--set-title", help="emit a terminal title escape"),
    ] = False,
) -> None:
    """Run a command in the workspace repo (alias for shell command mode)."""
    shell_cmd.open_workspace_shell(
        SimpleNamespace(
            workspace_name=workspace_name,
            shell=None,
            command=command or [],
            workspace_root=workspace_root,
            set_title=set_title,
        ),
        require_command=True,
    )


@app.command("list", help="List workspaces for the current project.")
def list_command() -> None:
    """List workspaces for the current project.

    Returns:
        None.

    Example:
        $ atelier list
    """
    list_cmd.list_workspaces(SimpleNamespace())


@app.command(
    "describe",
    help="Show project overview or detailed workspace status.",
)
def describe_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="workspace branch to describe (optional)",
            autocompletion=_workspace_only_shell_complete,
        ),
    ] = None,
    finalized: Annotated[
        bool,
        typer.Option(
            "--finalized",
            help="only show finalized workspaces (project scope)",
        ),
    ] = False,
    no_finalized: Annotated[
        bool,
        typer.Option(
            "--no-finalized",
            help="exclude finalized workspaces (project scope)",
        ),
    ] = False,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="output format (table|json)",
        ),
    ] = "table",
) -> None:
    """Describe project or workspace status."""
    describe_cmd(
        SimpleNamespace(
            workspace_name=workspace_name,
            finalized=finalized,
            no_finalized=no_finalized,
            format=format,
        )
    )


@app.command(
    "clean",
    help="Delete workspaces safely (finalization tag by default).",
)
def clean_command(
    all_: Annotated[
        bool,
        typer.Option("--all", "-A", help="delete all workspaces regardless of state"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="delete without confirmation"),
    ] = False,
    orphans: Annotated[
        bool,
        typer.Option(
            "--orphans",
            help="delete orphaned workspaces (missing config or repo dir)",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="show planned deletions only"),
    ] = False,
    no_branch: Annotated[
        bool,
        typer.Option("--no-branch", help="do not delete workspace branches"),
    ] = False,
    workspace_names: Annotated[
        list[str] | None,
        typer.Argument(
            help="workspace branches to delete",
            autocompletion=_workspace_only_shell_complete,
        ),
    ] = None,
) -> None:
    """Delete workspaces safely based on their status or explicit targets.

    Args:
        all_: Delete all workspaces regardless of state when true.
        yes: Delete without confirmation prompts when true.
        no_branch: Skip deleting local/remote workspace branches when true.
        workspace_names: Workspace branches to delete (optional).
        orphans: Delete orphaned workspaces when true.

    Returns:
        None.

    Example:
        $ atelier clean --all --yes
    """
    clean_cmd.clean_workspaces(
        SimpleNamespace(
            all=all_,
            yes=yes,
            orphans=orphans,
            dry_run=dry_run,
            no_branch=no_branch,
            workspace_names=workspace_names or [],
        )
    )


@app.command(
    "gc",
    help="Clean up stale hooks, claims, and orphaned worktrees.",
)
def gc_command(
    stale_hours: Annotated[
        float,
        typer.Option(
            "--stale-hours",
            help="consider heartbeats older than this many hours stale",
        ),
    ] = 24.0,
    stale_if_missing_heartbeat: Annotated[
        bool,
        typer.Option(
            "--stale-if-missing-heartbeat",
            help="treat missing heartbeats as stale",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="show planned actions only"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="apply without confirmation"),
    ] = False,
) -> None:
    """Garbage collect stale hooks and orphaned worktrees."""
    gc_cmd.gc(
        SimpleNamespace(
            stale_hours=stale_hours,
            stale_if_missing_heartbeat=stale_if_missing_heartbeat,
            dry_run=dry_run,
            yes=yes,
        )
    )


@app.command("config", help="Inspect or update Atelier configuration.")
def config_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="workspace branch to show config for (optional)",
            autocompletion=_workspace_only_shell_complete,
        ),
    ] = None,
    installed: Annotated[
        bool,
        typer.Option("--installed", help="operate on installed defaults"),
    ] = False,
    prompt: Annotated[
        bool,
        typer.Option("--prompt", help="prompt for user-editable settings"),
    ] = False,
    reset: Annotated[
        bool,
        typer.Option("--reset", help="reset user-editable settings to defaults"),
    ] = False,
    edit: Annotated[
        bool,
        typer.Option("--edit", help="edit user config in editor.edit"),
    ] = False,
) -> None:
    """Show or update Atelier configuration."""
    config_cmd.show_config(
        SimpleNamespace(
            workspace_name=workspace_name,
            installed=installed,
            prompt=prompt,
            reset=reset,
            edit=edit,
        )
    )


@app.command("policy", help="Edit project-wide agent policy.")
def policy_command(
    role: Annotated[
        str | None,
        typer.Option("--role", help="policy role (planner|worker|both)"),
    ] = None,
) -> None:
    """Edit project-wide policy stored in the planning store."""
    policy_cmd.edit_policy(SimpleNamespace(role=role))


@app.command("edit", help="Open the workspace repo in the work editor.")
def edit_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="workspace branch to open (optional)",
            autocompletion=_workspace_only_shell_complete,
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="treat the argument as the full branch name",
        ),
    ] = False,
    workspace_root: Annotated[
        bool,
        typer.Option("--workspace", help="open the workspace root instead of repo"),
    ] = False,
    set_title: Annotated[
        bool,
        typer.Option("--set-title", help="emit a terminal title escape"),
    ] = False,
) -> None:
    """Open the workspace repo in the configured work editor."""
    edit_cmd.open_workspace_editor(
        SimpleNamespace(
            workspace_name=workspace_name,
            raw=raw,
            workspace_root=workspace_root,
            set_title=set_title,
        )
    )


def main() -> None:
    """Run the Atelier CLI application.

    Returns:
        None.

    Example:
        >>> from atelier.cli import main
        >>> callable(main)
        True
    """
    _ensure_completion_env()
    app()


if __name__ == "__main__":
    main()
