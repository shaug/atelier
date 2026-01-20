"""Command-line interface entrypoint for Atelier.

Defines the Typer app, global options, and subcommands that delegate to the
implementation modules under ``atelier.commands``.

Example:
    $ atelier --help
"""

from types import SimpleNamespace
from typing import Annotated

import typer

from . import __version__
from .commands import clean as clean_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import open as open_cmd

app = typer.Typer(
    add_completion=False,
    help=(
        "Workspace-first CLI for managing isolated, agent-assisted work. "
        "Use 'atelier init' to register a repo, then 'atelier open' to create "
        "or resume a workspace that owns its own checkout and agent session."
    ),
)


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
    agent: Annotated[str | None, typer.Option("--agent", help="agent name")] = None,
    editor: Annotated[
        str | None, typer.Option("--editor", help="editor command")
    ] = None,
) -> None:
    """Initialize an Atelier project for the current Git repo.

    Args:
        branch_prefix: Prefix for new workspace branches (optional).
        branch_pr: Whether workspace branches expect pull requests (true/false).
        branch_history: History policy (manual|squash|merge|rebase).
        agent: Agent name (currently only ``codex``).
        editor: Editor command used to open ``SUCCESS.md``.
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
            editor=editor,
        )
    )


@app.command(
    "open",
    help="Create or open a workspace, ensure its checkout, then launch Codex.",
)
def open_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="workspace branch (defaults to current branch when criteria are met)",
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
) -> None:
    """Open or create a workspace and launch the agent.

    Args:
        workspace_name: Workspace branch name. When omitted, the current branch
            may be used if it meets the implicit-open criteria.
        raw: Treat the argument as the full branch name (no prefix lookup).
        branch_pr: Override pull request expectation (true/false).
        branch_history: Override history policy (manual|squash|merge|rebase).

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
        )
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


def main() -> None:
    """Run the Atelier CLI application.

    Returns:
        None.

    Example:
        >>> from atelier.cli import main
        >>> callable(main)
        True
    """
    app()


if __name__ == "__main__":
    main()
