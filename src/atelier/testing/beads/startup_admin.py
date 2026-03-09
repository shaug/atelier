"""Tier 2/3 in-memory Beads command emulation for runtime-focused tests."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from atelier import exec as exec_util

from .dispatcher import (
    CommandEnvelope,
    CommandInvocation,
    InMemoryBeadsCommandBackend,
    InMemoryBeadsDispatcher,
)

DEFAULT_PRIME_OUTPUT = "primed\n"
DEFAULT_PRIME_FULL_OUTPUT = (
    "## Beads Workflow Context\n\n"
    "```\n"
    "[ ] bd export\n"
    "[ ] bd sync --export\n"
    "[ ] bd dolt commit\n"
    "```\n"
    "- Runtime-close checklist.\n"
)
DEFAULT_CORE_TYPES = ("task",)


def _stats_payload(total: int) -> dict[str, object]:
    return {"summary": {"total_issues": total}}


def _normalize_types(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return tuple(normalized)


@dataclass
class InMemoryStartupAdminState:
    """Mutable state for startup/admin command emulation.

    Args:
        beads_root: Optional Beads root used when the backend should materialize
            a synthetic legacy SQLite file or Dolt store marker.
        issue_prefix: Current configured issue prefix.
        core_types: Core issue types returned by `bd types --json`.
        custom_types: Configured custom issue types.
        beads_role: Current `beads.role` config value.
        dolt_auto_commit: Current `dolt.auto-commit` config value.
        dolt_database: Active Dolt database name.
        dolt_connection_ok: Whether `bd dolt show --json` should report a
            healthy connection.
        has_dolt_store: Whether the synthetic `.dolt` store exists on disk.
        has_legacy_sqlite: Whether the synthetic `beads.db` file exists on disk.
        active_stats_replies: Replies returned by `bd stats --json`.
        legacy_stats_replies: Replies returned by legacy `bd --db ... stats`.
        rename_pending_count: Synthetic issue-count summary for prefix dry runs.
        prime_output: Stdout for `bd prime`.
        prime_full_output: Stdout for `bd prime --full`.
        vc_status_payload: JSON payload for `bd vc status --json`.
        doctor_reply: Reply for `bd doctor`.
        migrate_inspect_reply: Reply for
            `bd migrate --to-dolt --inspect --json`.
        migrate_apply_reply: Optional explicit reply for `bd migrate --to-dolt
            --yes --json`.
        dolt_show_reply: Optional explicit reply override for `bd dolt show`.
        dolt_set_database_reply: Optional explicit reply override for `bd dolt
            set database`.
        call_log: Captured command argv values for assertions.
    """

    beads_root: Path | None = None
    issue_prefix: str = "at"
    core_types: tuple[str, ...] = DEFAULT_CORE_TYPES
    custom_types: tuple[str, ...] = ()
    beads_role: str = ""
    dolt_auto_commit: str = "off"
    dolt_database: str = "beads_at"
    dolt_connection_ok: bool = True
    has_dolt_store: bool = True
    has_legacy_sqlite: bool = False
    active_stats_replies: list[CommandEnvelope] = field(
        default_factory=lambda: [CommandEnvelope.json_payload(_stats_payload(0))]
    )
    legacy_stats_replies: list[CommandEnvelope] = field(default_factory=list)
    rename_pending_count: int = 0
    prime_output: str = DEFAULT_PRIME_OUTPUT
    prime_full_output: str = DEFAULT_PRIME_FULL_OUTPUT
    vc_status_payload: dict[str, object] = field(
        default_factory=lambda: {"working_set": [0, False, {"pending": 0}]}
    )
    doctor_reply: CommandEnvelope = field(default_factory=lambda: CommandEnvelope(stdout="ok\n"))
    migrate_inspect_reply: CommandEnvelope = field(
        default_factory=lambda: CommandEnvelope.json_payload({"inspect": "ok"})
    )
    migrate_apply_reply: CommandEnvelope | None = None
    dolt_show_reply: CommandEnvelope | None = None
    dolt_set_database_reply: CommandEnvelope | None = None
    call_log: list[tuple[str, ...]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.core_types = _normalize_types(self.core_types or DEFAULT_CORE_TYPES)
        self.custom_types = _normalize_types(self.custom_types)
        self._materialize_store_markers()

    def _materialize_store_markers(self) -> None:
        if self.beads_root is None:
            return
        self.beads_root.mkdir(parents=True, exist_ok=True)
        if self.has_legacy_sqlite:
            (self.beads_root / "beads.db").write_bytes(b"legacy")
        if self.has_dolt_store:
            (self.beads_root / "dolt" / self.dolt_database / ".dolt").mkdir(
                parents=True, exist_ok=True
            )

    def _active_stats_reply(self) -> CommandEnvelope:
        return _consume_reply(
            self.active_stats_replies,
            fallback=CommandEnvelope.json_payload(_stats_payload(0)),
        )

    def _legacy_stats_reply(self) -> CommandEnvelope:
        fallback = (
            self.active_stats_replies[-1]
            if self.active_stats_replies
            else self._active_stats_reply()
        )
        return _consume_reply(self.legacy_stats_replies, fallback=fallback)

    def config_value(self, key: str) -> str:
        if key == "issue_prefix":
            return self.issue_prefix
        if key == "types.custom":
            return ",".join(self.custom_types)
        if key == "beads.role":
            return self.beads_role
        if key == "dolt.auto-commit":
            return self.dolt_auto_commit
        return ""

    def set_config_value(self, key: str, value: str) -> None:
        if key == "issue_prefix":
            self.issue_prefix = value.strip()
            return
        if key == "types.custom":
            self.custom_types = _normalize_types(value.split(","))
            return
        if key == "beads.role":
            self.beads_role = value.strip()
            return
        if key == "dolt.auto-commit":
            self.dolt_auto_commit = value.strip()

    def types_payload(self) -> dict[str, object]:
        core = [{"name": value} for value in self.core_types]
        custom = [{"name": value} for value in self.custom_types]
        return {
            "core_types": core,
            "custom_types": custom,
            "types": [*core, *custom],
        }

    def rename_prefix_detail(self, *, dry_run: bool, target_prefix: str) -> str:
        current_prefix = self.issue_prefix
        action = "Would rename" if dry_run else "Renamed"
        lines = [
            f"{'DRY RUN: ' if dry_run else ''}{action} {self.rename_pending_count} issues "
            f"from prefix '{current_prefix}' to '{target_prefix}'"
        ]
        if self.rename_pending_count > 0:
            lines.extend(
                [
                    "",
                    "Sample changes:",
                    f"  {current_prefix}-one -> {target_prefix}-one",
                    f"  {current_prefix}-two -> {target_prefix}-two",
                ]
            )
        return "\n".join(lines) + "\n"

    def record_call(self, invocation: CommandInvocation) -> None:
        self.call_log.append(tuple(invocation.argv))

    def migration_total(self) -> int:
        if self.migrate_apply_reply is not None:
            payload = json.loads(self.migrate_apply_reply.stdout or "{}")
            migrated = payload.get("migrated")
            if isinstance(migrated, int):
                return migrated
        for reply in reversed(self.legacy_stats_replies or self.active_stats_replies):
            payload = json.loads(reply.stdout or "{}")
            total = _stats_payload_from_payload(payload)
            if total is not None:
                return total
        return 0

    def mark_migrated(self) -> None:
        self.has_dolt_store = True
        if self.beads_root is not None:
            (self.beads_root / "dolt" / self.dolt_database / ".dolt").mkdir(
                parents=True, exist_ok=True
            )
        migrated_total = self.migration_total()
        self.active_stats_replies = [CommandEnvelope.json_payload(_stats_payload(migrated_total))]


def _stats_payload_from_payload(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    value = summary.get("total_issues")
    return value if isinstance(value, int) else None


def _consume_reply(queue: list[CommandEnvelope], *, fallback: CommandEnvelope) -> CommandEnvelope:
    if not queue:
        return fallback
    if len(queue) == 1:
        return queue[0]
    return queue.pop(0)


def _flag_value(tokens: Sequence[str], flag: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == flag:
            if index + 1 < len(tokens):
                return tokens[index + 1]
            return ""
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    return None


def _has_flag(tokens: Sequence[str], flag: str) -> bool:
    return flag in tokens


def _normalize_target_prefix(value: str) -> str:
    return value.strip().rstrip("-").strip()


def _db_flag_present(global_tokens: Sequence[str]) -> bool:
    return _flag_value(global_tokens, "--db") is not None


class InMemoryStartupAdminBackend(InMemoryBeadsCommandBackend):
    """Stateful in-memory backend for startup/admin command families."""

    def __init__(self, *, state: InMemoryStartupAdminState) -> None:
        self.state = state
        self._dispatcher = InMemoryBeadsDispatcher(
            family_handlers={
                "startup-config": self._handle_startup_config,
                "runtime-admin": self._handle_runtime_admin,
            }
        )

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self._dispatcher.run(argv, cwd=cwd, env=env)

    def _handle_startup_config(
        self,
        route,
        invocation: CommandInvocation,
    ) -> CommandEnvelope:
        self.state.record_call(invocation)
        tokens = invocation.command_tokens
        if route.command == ("prime",):
            if _has_flag(tokens, "--full"):
                return CommandEnvelope(stdout=self.state.prime_full_output)
            return CommandEnvelope(stdout=self.state.prime_output)
        if route.command == ("init",):
            prefix = _flag_value(tokens, "--prefix")
            if prefix:
                self.state.issue_prefix = prefix.strip()
            self.state.has_legacy_sqlite = True
            self.state._materialize_store_markers()
            return CommandEnvelope(stdout="initialized\n")
        if route.command == ("config", "get"):
            key_index = len(route.command)
            if key_index >= len(tokens):
                return CommandEnvelope.usage_error("missing config key")
            key = tokens[key_index]
            return CommandEnvelope.json_payload({"key": key, "value": self.state.config_value(key)})
        if route.command == ("config", "set"):
            value_index = len(route.command)
            if value_index + 1 >= len(tokens):
                return CommandEnvelope.usage_error("missing config value")
            key = tokens[value_index]
            value = tokens[value_index + 1]
            self.state.set_config_value(key, value)
            return CommandEnvelope(stdout="ok\n")
        if route.command == ("types",):
            return CommandEnvelope.json_payload(self.state.types_payload())
        if route.command == ("rename-prefix",):
            target_index = len(route.command)
            if target_index >= len(tokens):
                return CommandEnvelope.usage_error("missing target prefix")
            target_prefix = _normalize_target_prefix(tokens[target_index])
            if not _has_flag(tokens, "--repair"):
                return CommandEnvelope.usage_error("rename-prefix requires --repair")
            dry_run = _has_flag(tokens, "--dry-run")
            detail = self.state.rename_prefix_detail(
                dry_run=dry_run,
                target_prefix=target_prefix,
            )
            if not dry_run:
                self.state.issue_prefix = target_prefix
            return CommandEnvelope(stdout=detail)
        return CommandEnvelope.usage_error("unsupported startup-config route")

    def _handle_runtime_admin(
        self,
        route,
        invocation: CommandInvocation,
    ) -> CommandEnvelope:
        self.state.record_call(invocation)
        tokens = invocation.command_tokens
        if route.command == ("stats",):
            if _db_flag_present(invocation.global_tokens):
                return self.state._legacy_stats_reply()
            return self.state._active_stats_reply()
        if route.command == ("doctor",):
            return self.state.doctor_reply
        if route.command == ("migrate",):
            if _has_flag(tokens, "--inspect"):
                return self.state.migrate_inspect_reply
            if _has_flag(tokens, "--yes"):
                if self.state.migrate_apply_reply is not None:
                    self.state.mark_migrated()
                    return self.state.migrate_apply_reply
                self.state.mark_migrated()
                return CommandEnvelope.json_payload({"migrated": self.state.migration_total()})
            return CommandEnvelope.usage_error("migrate requires --inspect or --yes")
        if route.command == ("dolt", "show"):
            if self.state.dolt_show_reply is not None:
                return self.state.dolt_show_reply
            return CommandEnvelope.json_payload(
                {
                    "backend": "dolt",
                    "connection_ok": self.state.dolt_connection_ok,
                    "database": self.state.dolt_database,
                }
            )
        if route.command == ("dolt", "set", "database"):
            database_index = len(route.command)
            if database_index >= len(tokens):
                return CommandEnvelope.usage_error("missing database name")
            self.state.dolt_database = tokens[database_index].strip()
            if self.state.dolt_set_database_reply is not None:
                return self.state.dolt_set_database_reply
            return CommandEnvelope(stdout="ok\n")
        if route.command == ("dolt", "commit"):
            return CommandEnvelope(stdout="committed\n")
        if route.command == ("vc", "status"):
            return CommandEnvelope.json_payload(self.state.vc_status_payload)
        return CommandEnvelope.usage_error("unsupported runtime-admin route")


@dataclass(frozen=True)
class InMemoryStartupAdminFixture:
    """Bundled filesystem state plus exec-runner adapter for runtime tests."""

    beads_root: Path
    repo_root: Path
    state: InMemoryStartupAdminState
    backend: InMemoryStartupAdminBackend
    runner: "InMemoryBeadsCommandRunner"


class InMemoryBeadsCommandRunner(exec_util.CommandRunner):
    """Adapter that exposes an in-memory backend as an `atelier.exec` runner."""

    def __init__(self, *, backend: InMemoryBeadsCommandBackend) -> None:
        self._backend = backend

    def run(self, request: exec_util.CommandRequest) -> exec_util.CommandResult | None:
        completed = self._backend.run(request.argv, cwd=request.cwd, env=request.env)
        return exec_util.CommandResult(
            argv=tuple(str(token) for token in completed.args),
            returncode=completed.returncode,
            stdout=completed.stdout if isinstance(completed.stdout, str) else "",
            stderr=completed.stderr if isinstance(completed.stderr, str) else "",
        )


def build_startup_admin_fixture(
    tmp_path: Path,
    *,
    has_dolt_store: bool,
    legacy_issue_total: int | None = None,
    dolt_issue_totals: Sequence[int] = (0,),
    rename_pending_count: int = 0,
    dolt_auto_commit: str = "off",
    issue_prefix: str = "at",
    dolt_connection_ok: bool = True,
    vc_status_payload: dict[str, object] | None = None,
    migrate_inspect_reply: CommandEnvelope | None = None,
    migrate_apply_reply: CommandEnvelope | None = None,
    prime_full_output: str = DEFAULT_PRIME_FULL_OUTPUT,
) -> InMemoryStartupAdminFixture:
    """Create a deterministic fixture with on-disk startup/admin markers."""

    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    dolt_database = f"beads_{issue_prefix}"
    active_replies = [
        CommandEnvelope.json_payload(_stats_payload(total)) for total in tuple(dolt_issue_totals)
    ]
    legacy_replies = (
        [CommandEnvelope.json_payload(_stats_payload(legacy_issue_total))]
        if legacy_issue_total is not None
        else []
    )
    state = InMemoryStartupAdminState(
        beads_root=beads_root,
        issue_prefix=issue_prefix,
        dolt_auto_commit=dolt_auto_commit,
        dolt_database=dolt_database,
        dolt_connection_ok=dolt_connection_ok,
        has_dolt_store=has_dolt_store,
        has_legacy_sqlite=legacy_issue_total is not None,
        active_stats_replies=active_replies,
        legacy_stats_replies=legacy_replies,
        rename_pending_count=rename_pending_count,
        prime_full_output=prime_full_output,
        vc_status_payload=(
            vc_status_payload
            if vc_status_payload is not None
            else {"working_set": [0, False, {"pending": 0}]}
        ),
        migrate_inspect_reply=(
            migrate_inspect_reply
            if migrate_inspect_reply is not None
            else CommandEnvelope.json_payload({"inspect": "ok"})
        ),
        migrate_apply_reply=migrate_apply_reply,
    )
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server", "dolt_database": dolt_database})
        + "\n",
        encoding="utf-8",
    )
    backend = InMemoryStartupAdminBackend(state=state)
    runner = InMemoryBeadsCommandRunner(backend=backend)
    return InMemoryStartupAdminFixture(
        beads_root=beads_root,
        repo_root=repo_root,
        state=state,
        backend=backend,
        runner=runner,
    )


__all__ = [
    "DEFAULT_PRIME_FULL_OUTPUT",
    "DEFAULT_PRIME_OUTPUT",
    "InMemoryBeadsCommandRunner",
    "InMemoryStartupAdminBackend",
    "InMemoryStartupAdminFixture",
    "InMemoryStartupAdminState",
    "build_startup_admin_fixture",
]
