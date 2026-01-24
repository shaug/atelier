"""Command-line interface entrypoint for Atelier.

Defines the Typer app, global options, and subcommands that delegate to the
implementation modules under ``atelier.commands``.

Example:
    $ atelier --help
"""

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

from . import __version__, config, git, paths, workspace
from .commands import clean as clean_cmd
from .commands import config as config_cmd
from .commands import edit as edit_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import new as new_cmd
from .commands import open as open_cmd
from .commands import shell as shell_cmd
from .commands import snapshot as snapshot_cmd
from .commands import template as template_cmd
from .commands import upgrade as upgrade_cmd
from .commands import work as work_cmd
from .exec import try_run_command

app = typer.Typer(
    add_completion=True,
    help=(
        "Workspace-first CLI for managing isolated, agent-assisted work. "
        "Use 'atelier init' to register a repo, then 'atelier open' to create "
        "or resume a workspace that owns its own checkout and agent session."
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


def _collect_local_branches(
    repo_root: Path, git_path: str | None, prefix: str, *, allow_all: bool = False
) -> list[str]:
    if not prefix and not allow_all:
        return []
    ref_glob = "refs/heads" if not prefix else f"refs/heads/{prefix}*"
    cmd = git.git_command(
        ["-C", str(repo_root), "for-each-ref", "--format=%(refname:short)", ref_glob],
        git_path=git_path,
    )
    result = try_run_command(cmd)
    if not result or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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
    repo_root, project_root, config_payload, git_path = resolved
    try:
        workspaces = workspace.collect_workspaces(
            project_root,
            config_payload,
            with_status=False,
            enlistment_repo_dir=repo_root,
            git_path=git_path,
        )
    except Exception:
        workspaces = []
    names = [item.get("name", "") for item in workspaces if item.get("name")]
    names.extend(
        _collect_local_branches(repo_root, git_path, incomplete, allow_all=not names)
    )
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
        editor_edit: Editor command used for blocking edits (``SUCCESS.md``).
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
        editor_edit: Editor command used for blocking edits (``SUCCESS.md``).
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
    help="Create or open a workspace, ensure its checkout, then launch the agent.",
)
def open_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="workspace branch (defaults to current branch when criteria are met)",
            autocompletion=_workspace_name_shell_complete,
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="treat the argument as the full branch name",
        ),
    ] = False,
    branch_pr: Annotated[
        str | None,
        typer.Option(
            "--branch-pr",
            help="override pull request expectation (true/false)",
        ),
    ] = None,
    branch_history: Annotated[
        str | None,
        typer.Option(
            "--branch-history",
            help="override history policy (manual|squash|merge|rebase)",
        ),
    ] = None,
    ticket: Annotated[
        list[str] | None,
        typer.Option(
            "--ticket",
            help="ticket reference (repeatable or comma-separated)",
        ),
    ] = None,
    yolo: Annotated[
        bool,
        typer.Option(
            "--yolo",
            help="enable least-restrictive agent mode for this invocation",
        ),
    ] = False,
) -> None:
    """Open or create a workspace and launch the agent.

    Args:
        workspace_name: Workspace branch name. When omitted, the current branch
            may be used if it meets the implicit-open criteria.
        raw: Treat the argument as the full branch name (no prefix lookup).
        branch_pr: Override pull request expectation (true/false).
        branch_history: Override history policy (manual|squash|merge|rebase).
        ticket: Ticket reference(s) to attach to the workspace.
        yolo: Enable least-restrictive agent mode for this invocation.

    Returns:
        None.

    Example:
        $ atelier open feat/new-search
    """
    open_cmd.open_workspace(
        SimpleNamespace(
            workspace_name=workspace_name,
            raw=raw,
            branch_pr=branch_pr,
            branch_history=branch_history,
            ticket=ticket,
            yolo=yolo,
        )
    )


@app.command("work", help="Open the workspace repo in your work editor.")
def work_command(
    workspace_name: Annotated[
        str,
        typer.Argument(help="workspace branch to open"),
    ],
) -> None:
    """Open the workspace repo in the configured work editor."""
    work_cmd.open_workspace_repo(SimpleNamespace(workspace_name=workspace_name))


@app.command("snapshot", help="Write a workspace snapshot summary.")
def snapshot_command(
    workspace_name: Annotated[
        str,
        typer.Argument(
            help="workspace branch to snapshot",
            autocompletion=_workspace_name_shell_complete,
        ),
    ],
) -> None:
    """Write a snapshot summary for a workspace."""
    snapshot_cmd.snapshot_workspace(SimpleNamespace(workspace_name=workspace_name))


@app.command(
    "shell",
    help="Open a shell in the workspace repo or run a command there.",
)
def shell_command(
    workspace_name: Annotated[
        str,
        typer.Argument(help="workspace branch to open"),
    ],
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="shell path or name for interactive mode"),
    ] = None,
    command: Annotated[
        list[str] | None,
        typer.Argument(help="command to run in the workspace repo"),
    ] = None,
) -> None:
    """Open a shell in the workspace repo or run a command there."""
    shell_cmd.open_workspace_shell(
        SimpleNamespace(
            workspace_name=workspace_name,
            shell=shell,
            command=command or [],
        )
    )


@app.command(
    "exec",
    help="Run a command in the workspace repo (alias for shell command mode).",
)
def exec_command(
    workspace_name: Annotated[
        str,
        typer.Argument(help="workspace branch to open"),
    ],
    command: Annotated[
        list[str] | None,
        typer.Argument(help="command to run in the workspace repo"),
    ] = None,
) -> None:
    """Run a command in the workspace repo (alias for shell command mode)."""
    shell_cmd.open_workspace_shell(
        SimpleNamespace(
            workspace_name=workspace_name,
            shell=None,
            command=command or [],
        ),
        require_command=True,
    )


@app.command("list", help="List workspaces for the current project.")
def list_command(
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            help="include workspace status columns",
        ),
    ] = False,
) -> None:
    """List workspaces for the current project.

    Args:
        status: When true, include status columns in the output.

    Returns:
        None.

    Example:
        $ atelier list --status
    """
    list_cmd.list_workspaces(SimpleNamespace(status=status))


@app.command(
    "clean",
    help="Delete workspaces safely (finalization tag by default).",
)
def clean_command(
    all_: Annotated[
        bool,
        typer.Option("--all", "-A", help="delete all workspaces regardless of state"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-F", help="delete without confirmation"),
    ] = False,
    no_branch: Annotated[
        bool,
        typer.Option("--no-branch", help="do not delete workspace branches"),
    ] = False,
    workspace_names: Annotated[
        list[str] | None,
        typer.Argument(help="workspace branches to delete"),
    ] = None,
) -> None:
    """Delete workspaces safely based on their status or explicit targets.

    Args:
        all_: Delete all workspaces regardless of state when true.
        force: Delete without confirmation prompts when true.
        no_branch: Skip deleting local/remote workspace branches when true.
        workspace_names: Workspace branches to delete (optional).

    Returns:
        None.

    Example:
        $ atelier clean --all --force
    """
    clean_cmd.clean_workspaces(
        SimpleNamespace(
            all=all_,
            force=force,
            no_branch=no_branch,
            workspace_names=workspace_names or [],
        )
    )


@app.command(
    "upgrade",
    help="Upgrade project/workspace metadata and templates safely.",
)
def upgrade_command(
    workspace_names: Annotated[
        list[str] | None,
        typer.Argument(help="workspace branches to upgrade"),
    ] = None,
    installed: Annotated[
        bool,
        typer.Option("--installed", help="refresh the installed template cache"),
    ] = False,
    all_projects: Annotated[
        bool,
        typer.Option("--all-projects", help="upgrade all projects in the data dir"),
    ] = False,
    no_projects: Annotated[
        bool,
        typer.Option("--no-projects", help="skip project upgrades"),
    ] = False,
    no_workspaces: Annotated[
        bool,
        typer.Option("--no-workspaces", help="skip workspace upgrades"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="show planned changes only"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="apply without confirmation"),
    ] = False,
) -> None:
    """Upgrade project/workspace metadata to current conventions."""
    upgrade_cmd.upgrade(
        SimpleNamespace(
            workspace_names=workspace_names or [],
            installed=installed,
            all_projects=all_projects,
            no_projects=no_projects,
            no_workspaces=no_workspaces,
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


@app.command("template", help="Print or edit Atelier templates.")
def template_command(
    target: Annotated[
        str,
        typer.Argument(help="template target (project|workspace|success)"),
    ],
    installed: Annotated[
        bool,
        typer.Option("--installed", help="use the installed template cache"),
    ] = False,
    ticket: Annotated[
        bool,
        typer.Option(
            "--ticket",
            help="use the ticket SUCCESS.md template for workspace targets",
        ),
    ] = False,
    edit: Annotated[
        bool,
        typer.Option("--edit", help="open the resolved template in editor.edit"),
    ] = False,
) -> None:
    """Print or edit templates for the current project."""
    template_cmd.render_template(
        SimpleNamespace(target=target, installed=installed, ticket=ticket, edit=edit)
    )


@app.command("edit", help="Open editable project/workspace documents.")
def edit_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(help="workspace branch to edit SUCCESS.md"),
    ] = None,
    project: Annotated[
        bool,
        typer.Option("--project", help="edit PROJECT.md for the current project"),
    ] = False,
) -> None:
    """Open editable project/workspace documents."""
    edit_cmd.edit_files(SimpleNamespace(workspace_name=workspace_name, project=project))


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
