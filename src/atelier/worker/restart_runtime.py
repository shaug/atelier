"""Worker relaunch-contract and runtime-fingerprint helpers."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .. import __file__ as atelier_package_file
from .. import __version__ as atelier_version

_RESTART_ATTEMPT_COUNT_ENV = "ATELIER_RESTART_ATTEMPT_COUNT"
_RESTART_WINDOW_STARTED_AT_ENV = "ATELIER_RESTART_WINDOW_STARTED_AT"
_RESTART_RETRY_NOT_BEFORE_ENV = "ATELIER_RESTART_RETRY_NOT_BEFORE"
_RESTART_LAST_FINGERPRINT_ENV = "ATELIER_RESTART_LAST_FINGERPRINT"
_RESTART_MAX_ATTEMPTS = 3
_RESTART_WINDOW_SECONDS = 300
_RESTART_BASE_BACKOFF_SECONDS = 15
_RESTART_MAX_BACKOFF_SECONDS = 300
_RUNTIME_ENV_KEYS = (
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYENV_VERSION",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "UV_PYTHON",
    "__PYVENV_LAUNCHER__",
)
_RUNTIME_ENV_PREFIXES = ("ATELIER_", "BEADS_", "BD_")


@dataclass(frozen=True)
class WorkerRelaunchContract:
    """Captured process contract required for a future self-reexec."""

    cwd: Path
    argv: tuple[str, ...]
    executable: str
    entry_kind: Literal["module", "script", "executable"]
    entry_value: str
    env: tuple[tuple[str, str], ...]

    def exec_argv(self) -> tuple[str, ...]:
        """Return the argument vector to use for a future ``execvpe`` call.

        Returns:
            Tuple containing the captured relaunch argv.
        """
        return self.argv

    def exec_env(self) -> dict[str, str]:
        """Return the preserved environment subset for relaunch.

        Returns:
            Dict containing the captured relaunch environment.
        """
        return dict(self.env)

    def exec_target(self) -> str:
        """Return the executable target for a future ``execvpe`` call.

        Returns:
            Executable path or command name used for relaunch.
        """
        if self.argv:
            return self.argv[0]
        return self.executable


@dataclass(frozen=True)
class WorkerRuntimeFingerprint:
    """Composite worker runtime identity for update detection."""

    version: str
    code_marker_kind: str
    code_marker: str
    package_root: Path

    def changed_from(self, previous: WorkerRuntimeFingerprint) -> bool:
        """Return whether this runtime fingerprint differs from ``previous``.

        Args:
            previous: Earlier startup/runtime fingerprint to compare against.

        Returns:
            ``True`` when the composite fingerprint changed.
        """
        return (
            self.version,
            self.code_marker_kind,
            self.code_marker,
        ) != (
            previous.version,
            previous.code_marker_kind,
            previous.code_marker,
        )


@dataclass(frozen=True)
class WorkerRestartLoopState:
    """Bounded restart-attempt state preserved across worker re-execs."""

    attempt_count: int = 0
    window_started_at: int | None = None
    retry_not_before: int | None = None
    last_fingerprint: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> WorkerRestartLoopState:
        """Build restart-loop state from preserved environment variables.

        Args:
            env: Environment mapping captured at worker startup.

        Returns:
            Parsed restart-loop state. Invalid values fail closed to defaults.
        """
        return cls(
            attempt_count=_parse_env_int(env.get(_RESTART_ATTEMPT_COUNT_ENV)),
            window_started_at=_parse_env_int_optional(env.get(_RESTART_WINDOW_STARTED_AT_ENV)),
            retry_not_before=_parse_env_int_optional(env.get(_RESTART_RETRY_NOT_BEFORE_ENV)),
            last_fingerprint=_normalize_env_string(env.get(_RESTART_LAST_FINGERPRINT_ENV)),
        )

    def normalized(self, *, now: int) -> WorkerRestartLoopState:
        """Reset stale loop state after the bounded retry window expires.

        Args:
            now: Current epoch timestamp in seconds.

        Returns:
            Restart state scoped to the active retry window.
        """
        if self.window_started_at is None:
            return WorkerRestartLoopState()
        if now - self.window_started_at >= _RESTART_WINDOW_SECONDS:
            return WorkerRestartLoopState()
        return self

    def remaining_cooldown(self, *, now: int) -> int:
        """Return remaining cooldown seconds before the next restart attempt.

        Args:
            now: Current epoch timestamp in seconds.

        Returns:
            Remaining cooldown seconds, or ``0`` when no cooldown applies.
        """
        if self.retry_not_before is None or now >= self.retry_not_before:
            return 0
        return self.retry_not_before - now

    def next_attempt(
        self,
        *,
        now: int,
        fingerprint: WorkerRuntimeFingerprint,
    ) -> WorkerRestartLoopState:
        """Return loop state after scheduling a guarded restart attempt.

        Args:
            now: Current epoch timestamp in seconds.
            fingerprint: Runtime fingerprint that triggered the restart.

        Returns:
            Updated state with incremented attempt count and cooldown.
        """
        active_window_start = self.window_started_at or now
        attempt_count = self.attempt_count + 1
        backoff = min(
            _RESTART_BASE_BACKOFF_SECONDS * (2 ** max(attempt_count - 1, 0)),
            _RESTART_MAX_BACKOFF_SECONDS,
        )
        return WorkerRestartLoopState(
            attempt_count=attempt_count,
            window_started_at=active_window_start,
            retry_not_before=now + backoff,
            last_fingerprint=fingerprint.code_marker,
        )

    def export_env(self) -> tuple[tuple[str, str], ...]:
        """Serialize loop state back into environment variables.

        Returns:
            Key/value tuples suitable for relaunch environment preservation.
        """
        return (
            (_RESTART_ATTEMPT_COUNT_ENV, str(self.attempt_count)),
            (
                _RESTART_WINDOW_STARTED_AT_ENV,
                str(self.window_started_at or 0),
            ),
            (
                _RESTART_RETRY_NOT_BEFORE_ENV,
                str(self.retry_not_before or 0),
            ),
            (_RESTART_LAST_FINGERPRINT_ENV, self.last_fingerprint or ""),
        )


@dataclass(frozen=True)
class WorkerRestartDecision:
    """Decision for whether an idle-boundary restart attempt is allowed."""

    should_restart: bool
    reason: Literal["restart", "cooldown", "max-attempts"]
    message: str
    current_fingerprint: WorkerRuntimeFingerprint
    startup_runtime: WorkerStartupRuntime


@dataclass(frozen=True)
class WorkerStartupRuntime:
    """Startup snapshot combining relaunch inputs and runtime fingerprint."""

    relaunch_contract: WorkerRelaunchContract
    startup_fingerprint: WorkerRuntimeFingerprint
    restart_loop_state: WorkerRestartLoopState = WorkerRestartLoopState()

    def capture_current_fingerprint(
        self,
        *,
        version: str | None = None,
        package_root: Path | None = None,
    ) -> WorkerRuntimeFingerprint:
        """Capture the current runtime fingerprint using this snapshot's root.

        Args:
            version: Optional version override for tests or diagnostics.
            package_root: Optional package root override.

        Returns:
            Newly captured runtime fingerprint.
        """
        return capture_worker_runtime_fingerprint(
            version=version or self.startup_fingerprint.version,
            package_root=package_root or self.startup_fingerprint.package_root,
        )

    def runtime_changed(
        self,
        *,
        version: str | None = None,
        package_root: Path | None = None,
    ) -> bool:
        """Return whether the current runtime differs from startup.

        Args:
            version: Optional version override for tests or diagnostics.
            package_root: Optional package root override.

        Returns:
            ``True`` when the current runtime fingerprint changed.
        """
        current = self.capture_current_fingerprint(version=version, package_root=package_root)
        return current.changed_from(self.startup_fingerprint)

    def plan_restart(self, *, now: int | None = None) -> WorkerRestartDecision | None:
        """Return a bounded restart decision when the runtime has changed.

        Args:
            now: Optional epoch timestamp override for tests.

        Returns:
            Restart decision when a runtime update is detected.
            Otherwise returns ``None``.
        """
        current_fingerprint = self.capture_current_fingerprint()
        if not current_fingerprint.changed_from(self.startup_fingerprint):
            return None
        current_time = now if now is not None else current_restart_timestamp()
        loop_state = self.restart_loop_state.normalized(now=current_time)
        wait_seconds = loop_state.remaining_cooldown(now=current_time)
        if wait_seconds:
            return WorkerRestartDecision(
                should_restart=False,
                reason="cooldown",
                message=(
                    "Runtime update detected but auto-restart is cooling down for "
                    f"{wait_seconds}s after attempt {loop_state.attempt_count}/"
                    f"{_RESTART_MAX_ATTEMPTS}; continuing with the current runtime."
                ),
                current_fingerprint=current_fingerprint,
                startup_runtime=self.with_restart_loop_state(loop_state),
            )
        if loop_state.attempt_count >= _RESTART_MAX_ATTEMPTS:
            return WorkerRestartDecision(
                should_restart=False,
                reason="max-attempts",
                message=(
                    "Runtime update detected but auto-restart is paused after "
                    f"{loop_state.attempt_count}/{_RESTART_MAX_ATTEMPTS} attempts in "
                    f"{_RESTART_WINDOW_SECONDS}s; continuing with the current runtime."
                ),
                current_fingerprint=current_fingerprint,
                startup_runtime=self.with_restart_loop_state(loop_state),
            )
        next_state = loop_state.next_attempt(now=current_time, fingerprint=current_fingerprint)
        return WorkerRestartDecision(
            should_restart=True,
            reason="restart",
            message=(
                "Runtime update detected; restarting worker before the next idle "
                f"check (attempt {next_state.attempt_count}/{_RESTART_MAX_ATTEMPTS})."
            ),
            current_fingerprint=current_fingerprint,
            startup_runtime=self.with_restart_loop_state(next_state),
        )

    def with_restart_loop_state(
        self,
        restart_loop_state: WorkerRestartLoopState,
    ) -> WorkerStartupRuntime:
        """Return a copy with updated bounded restart-loop state.

        Args:
            restart_loop_state: Restart-loop state to preserve.

        Returns:
            Updated startup snapshot.
        """
        return WorkerStartupRuntime(
            relaunch_contract=self.relaunch_contract,
            startup_fingerprint=self.startup_fingerprint,
            restart_loop_state=restart_loop_state,
        )


def relaunch_worker_process(
    startup_runtime: WorkerStartupRuntime,
    *,
    chdir_fn: Callable[[Path], None] = os.chdir,
    execvpe_fn: Callable[[str, list[str], dict[str, str]], None] = os.execvpe,
) -> None:
    """Re-exec the current worker using its preserved launch contract.

    Args:
        startup_runtime: Startup snapshot containing the relaunch contract.
        chdir_fn: Injectable working-directory changer for tests.
        execvpe_fn: Injectable exec function for tests.

    Returns:
        This function does not return on successful ``execvpe``.
    """
    contract = startup_runtime.relaunch_contract
    chdir_fn(contract.cwd)
    env = contract.exec_env()
    env.update(dict(startup_runtime.restart_loop_state.export_env()))
    execvpe_fn(
        contract.exec_target(),
        list(contract.exec_argv()),
        env,
    )


def capture_worker_startup_runtime(
    *,
    argv: tuple[str, ...] | None = None,
    orig_argv: tuple[str, ...] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    executable: str | None = None,
    version: str | None = None,
    package_root: Path | None = None,
) -> WorkerStartupRuntime:
    """Capture relaunch inputs and runtime fingerprint at worker startup.

    Args:
        argv: Optional process argv override.
        orig_argv: Optional original interpreter argv override.
        env: Optional environment mapping override.
        cwd: Optional current-working-directory override.
        executable: Optional executable override.
        version: Optional Atelier version override.
        package_root: Optional package-root override.

    Returns:
        Startup runtime snapshot for future update detection and relaunch.
    """
    root = _resolve_package_root(package_root)
    return WorkerStartupRuntime(
        relaunch_contract=capture_worker_relaunch_contract(
            argv=argv,
            orig_argv=orig_argv,
            env=env,
            cwd=cwd,
            executable=executable,
        ),
        startup_fingerprint=capture_worker_runtime_fingerprint(
            version=version,
            package_root=root,
        ),
        restart_loop_state=WorkerRestartLoopState.from_env(os.environ if env is None else env),
    )


def capture_worker_relaunch_contract(
    *,
    argv: tuple[str, ...] | None = None,
    orig_argv: tuple[str, ...] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    executable: str | None = None,
) -> WorkerRelaunchContract:
    """Capture the worker process contract required for self-reexec.

    Args:
        argv: Optional process argv override.
        orig_argv: Optional original interpreter argv override.
        env: Optional environment mapping override.
        cwd: Optional current-working-directory override.
        executable: Optional executable override.

    Returns:
        Relaunch contract with cwd, argv, entry metadata, and env subset.
    """
    process_argv = _normalize_tokens(argv if argv is not None else tuple(sys.argv))
    process_orig_argv = _normalize_tokens(
        orig_argv if orig_argv is not None else tuple(getattr(sys, "orig_argv", ()))
    )
    resolved_executable = str(executable or sys.executable or "")
    launch_argv = _resolve_launch_argv(
        argv=process_argv,
        orig_argv=process_orig_argv,
        executable=resolved_executable,
    )
    entry_kind, entry_value = _resolve_entrypoint(launch_argv)
    source_env = os.environ if env is None else env
    resolved_cwd = cwd or Path.cwd()
    return WorkerRelaunchContract(
        cwd=resolved_cwd,
        argv=launch_argv,
        executable=resolved_executable,
        entry_kind=entry_kind,
        entry_value=entry_value,
        env=_capture_relaunch_env(source_env),
    )


def capture_worker_runtime_fingerprint(
    *,
    version: str | None = None,
    package_root: Path | None = None,
) -> WorkerRuntimeFingerprint:
    """Capture a composite runtime fingerprint for update detection.

    Args:
        version: Optional Atelier version override.
        package_root: Optional package-root override.

    Returns:
        Runtime fingerprint containing version and a code provenance marker.
    """
    resolved_root = _resolve_package_root(package_root)
    return WorkerRuntimeFingerprint(
        version=str(version or atelier_version),
        code_marker_kind="package-tree-stat-digest",
        code_marker=_package_tree_marker(resolved_root),
        package_root=resolved_root,
    )


def _normalize_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(token) for token in tokens if str(token))


def _normalize_env_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_env_int_optional(value: str | None) -> int | None:
    normalized = _normalize_env_string(value)
    if normalized is None:
        return None
    try:
        parsed = int(normalized)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_env_int(value: str | None) -> int:
    parsed = _parse_env_int_optional(value)
    return parsed or 0


def current_restart_timestamp() -> int:
    return int(time.time())


def _resolve_package_root(package_root: Path | None) -> Path:
    if package_root is not None:
        return package_root.resolve()
    return Path(str(atelier_package_file)).resolve().parent


def _resolve_launch_argv(
    *,
    argv: tuple[str, ...],
    orig_argv: tuple[str, ...],
    executable: str,
) -> tuple[str, ...]:
    if orig_argv:
        return orig_argv
    if argv:
        if argv[0] == executable:
            return argv
        if executable:
            return (executable, *argv)
        return argv
    if executable:
        return (executable,)
    return ()


def _resolve_entrypoint(
    argv: tuple[str, ...],
) -> tuple[Literal["module", "script", "executable"], str]:
    for index, token in enumerate(argv):
        if token == "-m" and index + 1 < len(argv):
            module_name = argv[index + 1].strip()
            if module_name:
                return "module", module_name
    if len(argv) >= 2:
        script_token = argv[1].strip()
        if script_token:
            script_path = Path(script_token)
            if script_path.suffix == ".py" or script_path.is_absolute():
                return "script", script_token
    if argv:
        return "executable", argv[0]
    return "executable", ""


def _capture_relaunch_env(env: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    captured: list[tuple[str, str]] = []
    for key in sorted(env):
        value = env.get(key)
        if value is None:
            continue
        if key in _RUNTIME_ENV_KEYS or key.startswith(_RUNTIME_ENV_PREFIXES):
            captured.append((key, str(value)))
    return tuple(captured)


def _package_tree_marker(package_root: Path) -> str:
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(_iter_fingerprint_files(package_root)):
        stat = path.stat()
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(b"\0")
        file_count += 1
    if file_count:
        return digest.hexdigest()
    digest.update(f"missing:{package_root}".encode("utf-8"))
    return digest.hexdigest()


def _iter_fingerprint_files(package_root: Path) -> list[Path]:
    if package_root.is_file():
        return [package_root]
    if not package_root.exists():
        return []
    files: list[Path] = []
    for candidate in package_root.rglob("*"):
        if not candidate.is_file():
            continue
        if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
            continue
        files.append(candidate)
    return files
