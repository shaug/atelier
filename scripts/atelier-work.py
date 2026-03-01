#!/usr/bin/env python3
"""Run a self-updating supervisor loop for Atelier worker sessions.

The runner ensures the enlistment is on the mainline branch (default: main),
then updates the checkout (fast-forward only), runs the install command
(default: just install), and runs one worker session per cycle. If HEAD is
not on the mainline branch, the update step is skipped and the cycle fails.

Examples:
  scripts/atelier-work.py --repo-path ~/code/atelier
  # (runs "just install" after update by default)

  scripts/atelier-work.py --repo-path ~/code/atelier --install "just install-editable"

  scripts/atelier-work.py --repo-path ~/code/atelier --no-install --dry-run -- --mode auto
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RunnerConfig:
    """Configuration for the supervisor loop."""

    repo_path: Path
    git_remote: str
    git_ref: str | None
    mainline_branch: str
    update_policy: str
    install_command: str | None
    worker_command: str
    loop_interval_seconds: float
    max_cycles: int | None
    dry_run: bool
    fail_fast: bool
    continue_on_worker_failure: bool


def _log(message: str) -> None:
    """Emit a prefixed log line to stdout."""

    print(f"[worker-supervisor] {message}")


def _split_passthrough_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split supervisor args from worker passthrough args.

    Args:
      argv: Command-line arguments excluding executable name.

    Returns:
      Tuple containing supervisor args and passthrough worker args.
    """

    args = list(argv)
    if "--" not in args:
        return args, []
    marker = args.index("--")
    return args[:marker], args[marker + 1 :]


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the supervisor script."""

    parser = argparse.ArgumentParser(
        description=("Run an update/install preflight before each one-shot Atelier worker cycle.")
    )
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Path to the Atelier checkout to update and run from (default: .)",
    )
    parser.add_argument(
        "--git-remote",
        default="origin",
        help="Git remote to fetch/pull for ff-only updates (default: origin)",
    )
    parser.add_argument(
        "--git-ref",
        default=None,
        help=("Git ref to pull from the remote. Defaults to current branch when omitted."),
    )
    parser.add_argument(
        "--mainline-branch",
        default="main",
        help=(
            "Branch that must be checked out before update (default: main). "
            "Update is skipped when HEAD is not this branch."
        ),
    )
    parser.add_argument(
        "--update-policy",
        choices=("ff-only", "skip"),
        default="ff-only",
        help="How to handle repo updates before each cycle (default: ff-only)",
    )
    parser.add_argument(
        "--install",
        nargs="?",
        default=None,
        const="just install",
        metavar="COMMAND",
        help=(
            "Run COMMAND after update (default: just install when omitted). "
            "Use --no-install to skip the install step."
        ),
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Skip the install step.",
    )
    parser.add_argument(
        "--worker-command",
        default="atelier work --run-mode once --yes",
        help=("Base worker command to run once per cycle. Arguments after '--' are appended."),
    )
    parser.add_argument(
        "--loop-interval-seconds",
        type=float,
        default=5.0,
        help="Sleep interval between cycles (default: 5)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional cycle limit. Defaults to infinite loop.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned update/install/worker actions without mutating state",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Exit immediately when update or install fails",
    )
    parser.add_argument(
        "--continue-on-worker-failure",
        action="store_true",
        help="Continue looping when the worker command exits non-zero",
    )
    return parser


def _parse_args(argv: Sequence[str]) -> tuple[RunnerConfig, list[str]]:
    """Parse command-line arguments into a typed runner configuration.

    Args:
      argv: Command-line arguments excluding executable name.

    Returns:
      Parsed runner config and passthrough worker args.

    Raises:
      SystemExit: When argument validation fails.
    """

    runner_argv, worker_passthrough = _split_passthrough_args(argv)
    args = _build_parser().parse_args(runner_argv)

    if args.loop_interval_seconds < 0:
        raise SystemExit("--loop-interval-seconds must be >= 0")
    if args.max_cycles is not None and args.max_cycles <= 0:
        raise SystemExit("--max-cycles must be > 0")

    max_cycles = args.max_cycles
    if args.dry_run and max_cycles is None:
        max_cycles = 1

    if args.no_install:
        install_command = None
    elif args.install is not None:
        install_command = (args.install.strip() or "just install") or None
    else:
        install_command = "just install"

    config = RunnerConfig(
        repo_path=Path(args.repo_path).expanduser().resolve(),
        git_remote=args.git_remote,
        git_ref=args.git_ref,
        mainline_branch=args.mainline_branch.strip() or "main",
        update_policy=args.update_policy,
        install_command=install_command,
        worker_command=args.worker_command,
        loop_interval_seconds=args.loop_interval_seconds,
        max_cycles=max_cycles,
        dry_run=args.dry_run,
        fail_fast=args.fail_fast,
        continue_on_worker_failure=args.continue_on_worker_failure,
    )
    return config, worker_passthrough


def _run_command(command: Sequence[str], *, cwd: Path | None, dry_run: bool) -> int:
    """Run a subprocess command and return its exit code.

    Args:
      command: Command and arguments to execute.
      cwd: Working directory for command execution.
      dry_run: Whether to skip command execution.

    Returns:
      Command exit code (always 0 in dry-run mode).
    """

    rendered = shlex.join(command)
    cwd_text = str(cwd) if cwd is not None else str(Path.cwd())
    if dry_run:
        _log(f"dry-run: would run in {cwd_text}: {rendered}")
        return 0

    _log(f"running in {cwd_text}: {rendered}")
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def _run_shell_command(command: str, *, cwd: Path, dry_run: bool) -> int:
    """Run a shell command through bash.

    Uses a non-login shell (-c) so the command inherits the current process
    environment (e.g. PATH, venv). A login shell (-lc) would source profile
    files and can switch to a different Python or tool chain.
    """

    return _run_command(["bash", "-c", command], cwd=cwd, dry_run=dry_run)


def _capture_output(command: Sequence[str], *, cwd: Path) -> str:
    """Run a command and return stripped stdout.

    Args:
      command: Command to execute.
      cwd: Working directory for command execution.

    Returns:
      Stripped standard output.

    Raises:
      RuntimeError: If the command exits non-zero.
    """

    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"command failed: {shlex.join(command)} :: {stderr}")
    return result.stdout.strip()


def _require_git_repo(repo_path: Path) -> None:
    """Validate that the configured path is a git working tree.

    Args:
      repo_path: Repository path to validate.

    Raises:
      RuntimeError: If path is not a valid git working tree.
    """

    _capture_output(
        ["git", "-C", str(repo_path), "rev-parse", "--is-inside-work-tree"],
        cwd=repo_path,
    )


def _current_branch(config: RunnerConfig) -> str:
    """Return the current branch name (short) for the repo."""
    return _capture_output(
        [
            "git",
            "-C",
            str(config.repo_path),
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
        ],
        cwd=config.repo_path,
    )


def _resolve_git_ref(config: RunnerConfig) -> str:
    """Resolve the git ref to pull from remote.

    Args:
      config: Runner configuration.

    Returns:
      Explicit git ref or current branch name.
    """

    if config.git_ref:
        return config.git_ref
    return _current_branch(config)


def _run_update_step(config: RunnerConfig) -> bool:
    """Run the repository update preflight step.

    Update runs only when the enlistment is on the configured mainline branch.
    Otherwise the step fails so the supervisor does not pull into a feature branch.

    Args:
      config: Runner configuration.

    Returns:
      ``True`` when the update step is successful or intentionally skipped.
    """

    if config.update_policy == "skip":
        _log("update: skipped by --update-policy=skip")
        return True

    try:
        current = _current_branch(config)
    except RuntimeError as exc:
        _log(f"update: failed to resolve current branch: {exc}")
        return False
    if current != config.mainline_branch:
        _log(
            f"update: not on mainline branch (current={current!r}, "
            f"mainline={config.mainline_branch!r}); skipping update"
        )
        return False

    try:
        ref = _resolve_git_ref(config)
    except RuntimeError as exc:
        _log(f"update: failed to resolve git ref: {exc}")
        return False
    _log(
        "update: fast-forward-only sync "
        f"remote={config.git_remote!r} ref={ref!r} repo={config.repo_path}"
    )
    fetch_rc = _run_command(
        [
            "git",
            "-C",
            str(config.repo_path),
            "fetch",
            "--prune",
            config.git_remote,
            ref,
        ],
        cwd=config.repo_path,
        dry_run=config.dry_run,
    )
    if fetch_rc != 0:
        _log("update: fetch failed")
        return False

    pull_rc = _run_command(
        [
            "git",
            "-C",
            str(config.repo_path),
            "pull",
            "--ff-only",
            config.git_remote,
            ref,
        ],
        cwd=config.repo_path,
        dry_run=config.dry_run,
    )
    if pull_rc != 0:
        _log("update: ff-only pull failed")
        return False

    _log("update: completed")
    return True


def _run_install_step(config: RunnerConfig) -> bool:
    """Run the optional install preflight command.

    Args:
      config: Runner configuration.

    Returns:
      ``True`` when install succeeds or is intentionally skipped.
    """

    if not config.install_command:
        _log("install: skipped (--no-install or no install command)")
        return True

    _log("install: running configured install command")
    install_rc = _run_shell_command(
        config.install_command,
        cwd=config.repo_path,
        dry_run=config.dry_run,
    )
    if install_rc != 0:
        _log("install: command failed")
        return False

    _log("install: completed")
    return True


def _build_worker_command(worker_command: str, worker_passthrough: Sequence[str]) -> list[str]:
    """Build the worker command and append passthrough arguments.

    Args:
      worker_command: Base worker command string.
      worker_passthrough: Additional args appended after ``--``.

    Returns:
      Fully tokenized worker command.

    Raises:
      RuntimeError: If worker command is empty.
    """

    command = shlex.split(worker_command)
    if not command:
        raise RuntimeError("worker command resolved to an empty command")
    command.extend(worker_passthrough)
    return command


def _run_worker_step(config: RunnerConfig, worker_passthrough: Sequence[str]) -> bool:
    """Run one worker session command.

    Args:
      config: Runner configuration.
      worker_passthrough: Additional args appended to worker command.

    Returns:
      ``True`` when worker command exits zero.
    """

    command = _build_worker_command(config.worker_command, worker_passthrough)
    _log("worker: running one worker cycle")
    worker_rc = _run_command(command, cwd=config.repo_path, dry_run=config.dry_run)
    if worker_rc != 0:
        _log("worker: command failed")
        return False
    _log("worker: completed")
    return True


def _run_cycle(config: RunnerConfig, worker_passthrough: Sequence[str], cycle_number: int) -> int:
    """Run one supervisor cycle.

    Args:
      config: Runner configuration.
      worker_passthrough: Additional worker command arguments.
      cycle_number: 1-based cycle number.

    Returns:
      ``0`` on success, ``1`` for preflight failures, ``2`` for worker failures.
    """

    _log(f"cycle {cycle_number}: starting")
    update_ok = _run_update_step(config)
    if not update_ok:
        _log("cycle: preflight failed; install and worker run skipped")
        return 1

    install_ok = _run_install_step(config)
    if not install_ok:
        _log("cycle: preflight failed; worker run skipped")
        return 1

    worker_ok = _run_worker_step(config, worker_passthrough)
    if not worker_ok:
        return 2

    _log(f"cycle {cycle_number}: done")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the supervisor loop.

    Args:
      argv: Optional args override. Uses ``sys.argv[1:]`` when omitted.

    Returns:
      Process exit code.
    """

    config, worker_passthrough = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    if not config.repo_path.exists():
        _log(f"error: repo path does not exist: {config.repo_path}")
        return 2

    try:
        _require_git_repo(config.repo_path)
    except RuntimeError as exc:
        _log(f"error: invalid git repository: {exc}")
        return 2

    if config.dry_run and config.max_cycles == 1:
        _log("dry-run: defaulting to one cycle; pass --max-cycles for more")

    cycle_number = 1
    saw_failure = False
    while True:
        cycle_rc = _run_cycle(config, worker_passthrough, cycle_number)
        if cycle_rc == 1:
            saw_failure = True
            if config.fail_fast:
                return 1
        elif cycle_rc == 2:
            saw_failure = True
            if not config.continue_on_worker_failure:
                return 2

        if config.max_cycles is not None and cycle_number >= config.max_cycles:
            _log(f"reached --max-cycles={config.max_cycles}; exiting")
            break

        cycle_number += 1
        if config.loop_interval_seconds <= 0:
            continue
        if config.dry_run:
            _log(f"dry-run: would sleep {config.loop_interval_seconds} seconds")
            continue
        _log(f"sleeping {config.loop_interval_seconds} seconds")
        time.sleep(config.loop_interval_seconds)

    return 1 if saw_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
