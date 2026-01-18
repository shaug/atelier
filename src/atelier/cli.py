from types import SimpleNamespace
from typing import Annotated

import typer

from . import __version__
from .commands import clean as clean_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import open as open_cmd

app = typer.Typer(add_completion=False)


def _version_callback(value: bool) -> None:
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
    """Atelier CLI."""


@app.command("init", help="initialize a project")
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
    workspace_template: Annotated[
        bool,
        typer.Option(
            "--workspace-template",
            help="create templates/WORKSPACE.md",
        ),
    ] = False,
) -> None:
    init_cmd.init_project(
        SimpleNamespace(
            branch_prefix=branch_prefix,
            branch_pr=branch_pr,
            branch_history=branch_history,
            agent=agent,
            editor=editor,
            workspace_template=workspace_template,
        )
    )


@app.command("open", help="open or create a workspace")
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
    open_cmd.open_workspace(
        SimpleNamespace(
            workspace_name=workspace_name,
            raw=raw,
            branch_pr=branch_pr,
            branch_history=branch_history,
        )
    )


@app.command("list", help="list workspaces")
def list_command(
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            help="include workspace status columns",
        ),
    ] = False,
) -> None:
    list_cmd.list_workspaces(SimpleNamespace(status=status))


@app.command("clean", help="clean workspaces")
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
    clean_cmd.clean_workspaces(
        SimpleNamespace(
            all=all_,
            force=force,
            no_branch=no_branch,
            workspace_names=workspace_names or [],
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
