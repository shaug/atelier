import argparse

from . import __version__
from .commands import clean as clean_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import open as open_cmd


def _init_command(args: argparse.Namespace) -> None:
    init_cmd.init_project(args)


def _open_command(args: argparse.Namespace) -> None:
    open_cmd.open_workspace(args)


def _list_command(args: argparse.Namespace) -> None:
    list_cmd.list_workspaces(args)


def _clean_command(args: argparse.Namespace) -> None:
    clean_cmd.clean_workspaces(args)


def main() -> None:
    parser = argparse.ArgumentParser(prog="atelier")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a project")
    init_parser.add_argument(
        "--branch-prefix", dest="branch_prefix", help="prefix for workspace branches"
    )
    init_parser.add_argument(
        "--branch-pr",
        dest="branch_pr",
        help="expect pull requests for workspace branches (true/false)",
    )
    init_parser.add_argument(
        "--branch-history",
        dest="branch_history",
        help="branch history policy (manual|squash|merge|rebase)",
    )
    init_parser.add_argument("--agent", dest="agent", help="agent name")
    init_parser.add_argument("--editor", dest="editor", help="editor command")
    init_parser.add_argument(
        "--workspace-template",
        action="store_true",
        help="create templates/WORKSPACE.md",
    )
    init_parser.set_defaults(func=_init_command)

    open_parser = subparsers.add_parser("open", help="open or create a workspace")
    open_parser.add_argument(
        "workspace_name",
        nargs="?",
        help="workspace branch (defaults to current branch when criteria are met)",
    )
    open_parser.add_argument(
        "--raw",
        action="store_true",
        help="treat the argument as the full branch name",
    )
    open_parser.add_argument(
        "--branch-pr",
        dest="branch_pr",
        help="override pull request expectation (true/false)",
    )
    open_parser.add_argument(
        "--branch-history",
        dest="branch_history",
        help="override history policy (manual|squash|merge|rebase)",
    )
    open_parser.set_defaults(func=_open_command)

    list_parser = subparsers.add_parser("list", help="list workspaces")
    list_parser.add_argument(
        "--status",
        action="store_true",
        help="include workspace status columns",
    )
    list_parser.set_defaults(func=_list_command)

    clean_parser = subparsers.add_parser("clean", help="clean workspaces")
    clean_parser.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="delete all workspaces regardless of state",
    )
    clean_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="delete without confirmation",
    )
    clean_parser.add_argument(
        "--no-branch",
        action="store_true",
        help="do not delete workspace branches",
    )
    clean_parser.add_argument(
        "workspace_names", nargs="*", help="workspace branches to delete"
    )
    clean_parser.set_defaults(func=_clean_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
