"""Manage the Atelier daemon (worker loop + bd daemon)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from .. import beads, config, exec, paths
from ..io import say
from .resolve import resolve_current_project_with_repo_root


def _daemon_dir(project_data_dir: Path) -> Path:
    return paths.project_daemon_dir(project_data_dir)


def _worker_pid_path(project_data_dir: Path) -> Path:
    return _daemon_dir(project_data_dir) / "worker.pid"


def _worker_log_path(project_data_dir: Path) -> Path:
    return _daemon_dir(project_data_dir) / "worker.log"


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _resolve_beads_db(beads_root: Path) -> Path | None:
    if not beads_root.exists():
        return None
    dbs = sorted(beads_root.glob("*.db"))
    if dbs:
        return dbs[0]
    return None


def _ensure_beads_db(beads_root: Path, project_data_dir: Path) -> Path:
    paths.ensure_dir(beads_root)
    db_path = beads_root / "atelier.db"
    if db_path.exists():
        return db_path
    args = [
        "bd",
        "init",
        "--db",
        str(db_path),
        "--skip-hooks",
        "--skip-merge-driver",
    ]
    if (beads_root / "issues.jsonl").exists():
        args.append("--from-jsonl")
    exec.run_command(args, cwd=project_data_dir, env=beads.beads_env(beads_root))
    return db_path


def _bd_daemon_status(
    *, beads_root: Path, project_data_dir: Path, db_path: Path | None
) -> dict[str, object] | None:
    if db_path is None:
        return None
    cmd = ["bd", "daemon", "status", "--json", "--db", str(db_path)]
    result = exec.try_run_command(cmd, cwd=project_data_dir, env=beads.beads_env(beads_root))
    if result is None or result.returncode != 0:
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _start_worker(project_data_dir: Path, repo_root: Path) -> int:
    paths.ensure_dir(_daemon_dir(project_data_dir))
    log_path = _worker_log_path(project_data_dir)
    log_file = log_path.open("a", encoding="utf-8")
    cmd = [
        "atelier",
        "work",
        "--mode",
        "auto",
        "--run-mode",
        "watch",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=repo_root,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    _worker_pid_path(project_data_dir).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def _stop_worker(project_data_dir: Path) -> bool:
    pid_path = _worker_pid_path(project_data_dir)
    pid = _read_pid(pid_path)
    if pid is None:
        return False
    if not _pid_running(pid):
        pid_path.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    pid_path.unlink(missing_ok=True)
    return True


def start_daemon(args: object) -> None:
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    db_path = _ensure_beads_db(beads_root, project_data_dir)
    status = _bd_daemon_status(
        beads_root=beads_root, project_data_dir=project_data_dir, db_path=db_path
    )
    bd_running = status is not None and status.get("status") == "running"

    worker_pid = _read_pid(_worker_pid_path(project_data_dir))
    worker_running = bool(worker_pid and _pid_running(worker_pid))

    if bd_running and worker_running:
        say("Daemon already running.")
        return

    if not bd_running:
        cmd = [
            "bd",
            "daemon",
            "start",
            "--db",
            str(db_path),
            "--log",
            str(beads_root / "daemon.log"),
        ]
        exec.run_command(cmd, cwd=project_data_dir, env=beads.beads_env(beads_root))
        say("Started bd daemon.")
    else:
        say("bd daemon already running.")

    if not worker_running:
        pid = _start_worker(project_data_dir, repo_root)
        say(f"Started worker daemon (pid {pid}).")
    else:
        say(f"Worker daemon already running (pid {worker_pid}).")


def stop_daemon(args: object) -> None:
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    stopped_worker = _stop_worker(project_data_dir)
    if stopped_worker:
        say("Stopped worker daemon.")
    else:
        say("Worker daemon not running.")

    db_path = _resolve_beads_db(beads_root)
    if db_path is None:
        say("bd daemon not configured.")
        return

    cmd = ["bd", "daemon", "stop", "--db", str(db_path)]
    result = exec.try_run_command(cmd, cwd=project_data_dir, env=beads.beads_env(beads_root))
    if result is None or result.returncode != 0:
        say("bd daemon not running.")
        return
    say("Stopped bd daemon.")


def status_daemon(args: object) -> None:
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    db_path = _resolve_beads_db(beads_root)
    status = _bd_daemon_status(
        beads_root=beads_root, project_data_dir=project_data_dir, db_path=db_path
    )
    if status is None:
        say("bd daemon: stopped")
    else:
        say(f"bd daemon: {status.get('status')}")

    pid = _read_pid(_worker_pid_path(project_data_dir))
    if pid and _pid_running(pid):
        say(f"worker daemon: running (pid {pid})")
    else:
        say("worker daemon: stopped")
