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
from typing import Annotated, Callable, cast

import click
import typer

try:
    from click.shell_completion import split_arg_string
except ImportError:  # pragma: no cover - legacy Click fallback
    from click.parser import split_arg_string

from . import __version__, bd_invocation, beads, config, git, lifecycle, paths
from . import log as atelier_log
from .commands import config as config_cmd
from .commands import doctor as doctor_cmd
from .commands import edit as edit_cmd
from .commands import gc as gc_cmd
from .commands import hook as hook_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import new as new_cmd
from .commands import open as open_cmd
from .commands import plan as plan_cmd
from .commands import policy as policy_cmd
from .commands import remove as remove_cmd
from .commands import repair_event_history as repair_event_history_cmd
from .commands import status as status_cmd
from .commands import work as work_cmd
from .exec import try_run_command
from .models import (
    BRANCH_HISTORY_VALUES,
    BRANCH_PR_MODE_VALUES,
    BRANCH_SQUASH_MESSAGE_VALUES,
    WORKER_SELECT_VALUES,
)

_split_arg_string = cast(Callable[[str], list[str]], split_arg_string)

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
_LOG_LEVEL_CHOICES = ("trace", "debug", "info", "success", "warning", "error")
_HOOK_EVENT_CHOICES = ("session-start", "pre-compact", "stop")
_WORK_MODE_CHOICES = ("prompt", "auto")
_RUN_MODE_CHOICES = ("once", "default", "watch")
_FORMAT_CHOICES = ("table", "json")
_POLICY_ROLE_CHOICES = ("planner", "worker", "both")


class _HyphenAliasChoice(click.Choice):
    """Choice type that accepts underscore aliases for hyphenated values."""

    def convert(
        self,
        value: object,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> object:
        if isinstance(value, str):
            value = value.strip().lower().replace("_", "-")
        return super().convert(value, param, ctx)


def _choice(values: tuple[str, ...]) -> click.Choice:
    """Build a case-insensitive choice type with underscore aliases."""
    return _HyphenAliasChoice(values, case_sensitive=False)


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
        words = _split_arg_string(line)
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
        repo_root, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd or Path.cwd())
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
    env = beads.beads_env(beads_root)
    cmd = bd_invocation.with_bd_mode(
        "list",
        "--label",
        beads.issue_label("epic", beads_root=beads_root),
        "--json",
        beads_dir=str(beads_root),
        env=env,
    )
    result = try_run_command(cmd, cwd=repo_root, env=env)
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
        if not lifecycle.is_active_root_branch_owner(
            status=issue.get("status"),
            labels=lifecycle.normalized_labels(issue.get("labels")),
        ):
            continue
        root_branch = beads.extract_workspace_root_branch(issue)
        if root_branch:
            roots.append(root_branch)
    return roots


def _filter_completion_candidates(values: list[str], incomplete: str) -> list[str]:
    filtered = [
        value
        for value in values
        if value and value.startswith(incomplete) and value not in _DEFAULT_BRANCH_EXCLUDES
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for value in filtered:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            help="set terminal log level (trace|debug|info|success|warning|error)",
            click_type=_choice(_LOG_LEVEL_CHOICES),
        ),
    ] = None,
    color: Annotated[
        bool | None,
        typer.Option(
            "--color/--no-color",
            help="enable or disable colorized terminal output",
        ),
    ] = None,
) -> None:
    """Workspace-first CLI for managing isolated, agent-assisted work.

    Args:
        version: When true, prints the CLI version and exits.
        log_level: Optional log level override for this CLI invocation.
        color: Optional color output override for this CLI invocation.

    Returns:
        None.

    Example:
        $ atelier init
    """
    if log_level is not None:
        normalized = log_level.strip().lower()
        if normalized not in _LOG_LEVEL_CHOICES:
            choices = ", ".join(_LOG_LEVEL_CHOICES)
            raise typer.BadParameter(
                f"expected one of: {choices}",
                param_hint="--log-level",
            )
        atelier_log.set_level(normalized)
    if color is not None:
        atelier_log.set_no_color(not color)


@app.command(
    "init",
    help="Register the current repo as an Atelier project in the data directory.",
)
def init_command(
    branch_prefix: Annotated[
        str | None,
        typer.Option("--branch-prefix", help="prefix for workspace branches"),
    ] = None,
    beads_prefix: Annotated[
        str | None,
        typer.Option(
            "--beads-prefix",
            help="Beads issue prefix (for example: at, ts, ts2)",
        ),
    ] = None,
    branch_pr_mode: Annotated[
        str | None,
        typer.Option(
            "--branch-pr-mode",
            "--branch-pr",
            help="workspace pull request mode (none|draft|ready)",
            click_type=_choice(BRANCH_PR_MODE_VALUES),
        ),
    ] = None,
    branch_history: Annotated[
        str | None,
        typer.Option(
            "--branch-history",
            help="branch history policy (manual|squash|merge|rebase)",
            click_type=_choice(BRANCH_HISTORY_VALUES),
        ),
    ] = None,
    branch_squash_message: Annotated[
        str | None,
        typer.Option(
            "--branch-squash-message",
            help="squash commit message policy (deterministic|agent)",
            click_type=_choice(BRANCH_SQUASH_MESSAGE_VALUES),
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
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="accept defaults for interactive choices",
        ),
    ] = False,
) -> None:
    """Initialize an Atelier project for the current Git repo.

    Args:
        branch_prefix: Prefix for new workspace branches (optional).
        beads_prefix: Prefix for Beads issue ids (for example: ``ts``).
        branch_pr_mode: Workspace PR mode (none|draft|ready).
        branch_history: History policy (manual|squash|merge|rebase).
        branch_squash_message: Squash commit subject policy
            (deterministic|agent).
        agent: Agent name.
        editor_edit: Editor command used for blocking edits (policy docs).
        editor_work: Editor command used for opening the workspace repo.
        yes: Accept defaults for interactive choices.
    Returns:
        None.

    Example:
        $ atelier init --branch-prefix scott/ --branch-history rebase
    """
    init_cmd.init_project(
        init_cmd.InitProjectArgs(
            branch_prefix=branch_prefix,
            beads_prefix=beads_prefix,
            branch_pr_mode=branch_pr_mode,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            agent=agent,
            editor_edit=editor_edit,
            editor_work=editor_work,
            yes=yes,
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
    beads_prefix: Annotated[
        str | None,
        typer.Option(
            "--beads-prefix",
            help="Beads issue prefix (for example: at, ts, ts2)",
        ),
    ] = None,
    branch_pr_mode: Annotated[
        str | None,
        typer.Option(
            "--branch-pr-mode",
            "--branch-pr",
            help="workspace pull request mode (none|draft|ready)",
            click_type=_choice(BRANCH_PR_MODE_VALUES),
        ),
    ] = None,
    branch_history: Annotated[
        str | None,
        typer.Option(
            "--branch-history",
            help="branch history policy (manual|squash|merge|rebase)",
            click_type=_choice(BRANCH_HISTORY_VALUES),
        ),
    ] = None,
    branch_squash_message: Annotated[
        str | None,
        typer.Option(
            "--branch-squash-message",
            help="squash commit message policy (deterministic|agent)",
            click_type=_choice(BRANCH_SQUASH_MESSAGE_VALUES),
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
        beads_prefix: Prefix for Beads issue ids (for example: ``ts``).
        branch_pr_mode: Workspace PR mode (none|draft|ready).
        branch_history: History policy (manual|squash|merge|rebase).
        branch_squash_message: Squash commit subject policy
            (deterministic|agent).
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
            beads_prefix=beads_prefix,
            branch_pr_mode=branch_pr_mode,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            agent=agent,
            editor_edit=editor_edit,
            editor_work=editor_work,
        )
    )


@app.command(
    "open",
    help="Open a shell (or run a command) in a workspace worktree.",
)
def open_command(
    workspace_name: Annotated[
        str | None,
        typer.Argument(
            help="changeset id (preferred) or workspace/branch alias to open",
            autocompletion=_workspace_only_shell_complete,
        ),
    ] = None,
    command: Annotated[
        list[str] | None,
        typer.Argument(help="command to run in the worktree"),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="do not apply the branch prefix"),
    ] = False,
    shell: Annotated[
        str | None,
        typer.Option("--shell", help="shell path or name for interactive mode"),
    ] = None,
    workspace_root: Annotated[
        bool,
        typer.Option("--workspace", help="open the worktree root"),
    ] = False,
    set_title: Annotated[
        bool,
        typer.Option("--set-title", help="emit a terminal title escape"),
    ] = False,
) -> None:
    """Open a shell or run a command in a worktree."""
    open_cmd.open_worktree(
        SimpleNamespace(
            workspace_name=workspace_name,
            command=command or [],
            raw=raw,
            shell=shell,
            workspace_root=workspace_root,
            set_title=set_title,
        )
    )


@app.command("plan", help="Start a planner session for Beads epics.")
def plan_command(
    epic_id: Annotated[
        str | None,
        typer.Option("--epic-id", help="existing epic bead id to plan against"),
    ] = None,
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="reconcile merged changesets before starting planner session",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="accept defaults for interactive choices",
        ),
    ] = False,
    new_session: Annotated[
        bool,
        typer.Option(
            "--new-session",
            help="always start a fresh planner session instead of resuming",
        ),
    ] = False,
    trace: Annotated[
        bool,
        typer.Option(
            "--trace",
            help="show planner step timing details",
        ),
    ] = False,
    yolo: Annotated[
        bool,
        typer.Option(
            "--yolo",
            help="enable the most permissive agent flags supported by the planner agent",
        ),
    ] = False,
) -> None:
    """Start a planner session."""
    plan_cmd.run_planner(
        SimpleNamespace(
            epic_id=epic_id,
            reconcile=reconcile,
            yes=yes,
            new_session=new_session,
            trace=trace,
            yolo=yolo,
        )
    )


@app.command("hook", help="Run an agent hook event handler.")
def hook_command(
    event: Annotated[
        str | None,
        typer.Argument(
            help="hook event name (session-start|pre-compact|stop)",
            click_type=_choice(_HOOK_EVENT_CHOICES),
        ),
    ] = None,
) -> None:
    """Run a hook command for agent integrations."""
    hook_cmd.run_hook(SimpleNamespace(event=event))


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
            help="worker selection mode: prompt or auto (default: prompt)",
            click_type=_choice(_WORK_MODE_CHOICES),
        ),
    ] = None,
    select: Annotated[
        str | None,
        typer.Option(
            "--select",
            help=(
                "startup selector policy: first-eligible or oldest-feedback "
                "(default: config worker.select, then oldest-feedback)"
            ),
            click_type=_choice(WORKER_SELECT_VALUES),
        ),
    ] = None,
    run_mode: Annotated[
        str | None,
        typer.Option(
            "--run-mode",
            help="worker run mode: once, default, watch (default: default)",
            click_type=_choice(_RUN_MODE_CHOICES),
        ),
    ] = None,
    restart_on_update: Annotated[
        bool,
        typer.Option(
            "--restart-on-update",
            help="restart workers at idle boundaries after runtime updates",
        ),
    ] = False,
    no_restart_on_update: Annotated[
        bool,
        typer.Option(
            "--no-restart-on-update",
            help="disable idle-boundary restart even when watch mode would enable it",
        ),
    ] = False,
    watch_interval: Annotated[
        int | None,
        typer.Option(
            "--watch-interval",
            help="watch polling interval in seconds (default: 60)",
        ),
    ] = None,
    queue: Annotated[
        bool,
        typer.Option(
            "--queue",
            help="process queued messages and exit",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="log what would happen without mutating state or starting the agent",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="accept defaults for interactive choices (default from ATELIER_WORK_YES)",
        ),
    ] = False,
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="reconcile merged changesets before startup contract",
        ),
    ] = False,
    yolo: Annotated[
        bool,
        typer.Option(
            "--yolo",
            help="enable the most permissive agent flags supported by the worker agent",
        ),
    ] = False,
) -> None:
    """Start a worker session."""
    if restart_on_update and no_restart_on_update:
        raise typer.BadParameter("cannot use both --restart-on-update and --no-restart-on-update")
    resolved_restart_on_update: bool | None = None
    if restart_on_update:
        resolved_restart_on_update = True
    elif no_restart_on_update:
        resolved_restart_on_update = False
    work_cmd.start_worker(
        SimpleNamespace(
            epic_id=epic_id,
            mode=mode,
            select=select,
            run_mode=run_mode,
            restart_on_update=resolved_restart_on_update,
            watch_interval=watch_interval,
            queue=queue,
            dry_run=dry_run,
            yes=yes,
            reconcile=reconcile,
            yolo=yolo,
        )
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


@app.command("status", help="Show epics, hooks, and changeset status.")
def status_command(
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="output format (table|json)",
            click_type=_choice(_FORMAT_CHOICES),
        ),
    ] = "table",
) -> None:
    """Show project status for epics, hooks, and changesets."""
    status_cmd(SimpleNamespace(format=format))


@app.command(
    "doctor",
    help="Run multi-check migration health diagnostics and optional drift repair.",
)
def doctor_command(
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="output format (table|json)",
            click_type=_choice(_FORMAT_CHOICES),
        ),
    ] = "table",
    fix: Annotated[
        bool,
        typer.Option(
            "--fix",
            help="apply drift repairs (default is read-only detection)",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="override active-hook deferrals when used with --fix",
        ),
    ] = False,
) -> None:
    """Run migration-health diagnostics and optional prefix-drift repair."""
    doctor_cmd(SimpleNamespace(format=format, fix=fix, force=force))


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
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="reconcile blocked merged changesets before GC actions",
        ),
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
            reconcile=reconcile,
            yes=yes,
        )
    )


@app.command(
    "repair-event-history-overflow",
    help="Repair a Beads issue whose event history overflowed and blocked mutation.",
)
def repair_event_history_overflow_command(
    issue_id: Annotated[
        str,
        typer.Argument(help="Beads issue id to repair"),
    ],
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="output format (table|json)",
            click_type=_choice(_FORMAT_CHOICES),
        ),
    ] = "table",
) -> None:
    """Repair a Beads issue whose event history overflowed."""
    repair_event_history_cmd.repair_event_history_overflow(
        SimpleNamespace(issue_id=issue_id, format=format)
    )


@app.command(
    "remove",
    help="Remove Atelier project state for the current repository.",
)
def remove_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="apply removal without confirmation"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="show what would be removed"),
    ] = False,
    gc: Annotated[
        bool,
        typer.Option(
            "--gc/--no-gc",
            help="run gc before deleting project data",
        ),
    ] = True,
    reconcile: Annotated[
        bool,
        typer.Option(
            "--reconcile",
            help="when --gc is enabled, reconcile merged changesets first",
        ),
    ] = False,
    prune_branches: Annotated[
        bool,
        typer.Option(
            "--prune-branches",
            help="also prune mapped local/remote branches (destructive)",
        ),
    ] = False,
) -> None:
    """Remove Atelier project data for the current repository."""
    remove_cmd.remove_project(
        SimpleNamespace(
            yes=yes,
            dry_run=dry_run,
            gc=gc,
            reconcile=reconcile,
            prune_branches=prune_branches,
        )
    )


@app.command("config", help="Inspect or update Atelier configuration.")
def config_command(
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
            installed=installed,
            prompt=prompt,
            reset=reset,
            edit=edit,
        )
    )


@app.command("policy", help="Show or edit project-wide agent policy.")
def policy_command(
    role: Annotated[
        str | None,
        typer.Option(
            "--role",
            help="policy role (planner|worker|both)",
            click_type=_choice(_POLICY_ROLE_CHOICES),
        ),
    ] = None,
    edit: Annotated[
        bool,
        typer.Option("--edit", help="edit policy in editor.edit"),
    ] = False,
) -> None:
    """Show policy by default; edit with --edit."""
    args = SimpleNamespace(role=role)
    if edit:
        policy_cmd.edit_policy(args)
        return
    policy_cmd.show_policy(args)


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
