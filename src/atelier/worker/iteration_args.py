"""Typed worker-iteration argument normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_DEFAULT_STARTUP_SELECT: Final[str] = "oldest-feedback"
_UNSET: Final[object] = object()


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_text(value: object, *, default: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return default
    return normalized


def _normalize_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    normalized: list[str] = []
    for item in value:
        text = _normalize_optional_text(item)
        if text:
            normalized.append(text)
    return tuple(normalized)


@dataclass
class WorkerIterationArgs:
    """Typed worker iteration arguments consumed by runtime and runner."""

    raw_args: object
    epic_id: str | None
    queue: bool
    yes: bool
    reconcile: bool
    select: str
    yolo: bool
    agent_bead_id: str | None
    implicit_excluded_epic_ids: tuple[str, ...]
    bounded_runtime_iteration_token: str | None
    restart_on_update: bool
    startup_runtime: object | None

    def __getattr__(self, name: str) -> object:
        """Fall back to wrapped raw args for non-modeled fields."""
        return getattr(self.raw_args, name)


def build_worker_iteration_args(
    raw_args: WorkerIterationArgs | object,
    *,
    epic_id: str | None | object = _UNSET,
    implicit_excluded_epic_ids: tuple[str, ...] | object = _UNSET,
    bounded_runtime_iteration_token: str | None | object = _UNSET,
    restart_on_update: bool | object = _UNSET,
    startup_runtime: object = _UNSET,
) -> WorkerIterationArgs:
    """Normalize raw args into a strongly typed worker iteration payload."""
    if isinstance(raw_args, WorkerIterationArgs):
        source_args = raw_args.raw_args
        resolved_epic_id = raw_args.epic_id
        resolved_queue = raw_args.queue
        resolved_yes = raw_args.yes
        resolved_reconcile = raw_args.reconcile
        resolved_select = raw_args.select
        resolved_yolo = raw_args.yolo
        resolved_agent_bead_id = raw_args.agent_bead_id
        resolved_excluded = raw_args.implicit_excluded_epic_ids
        resolved_iteration_token = raw_args.bounded_runtime_iteration_token
        resolved_restart_on_update = raw_args.restart_on_update
        resolved_startup_runtime = raw_args.startup_runtime
    else:
        source_args = raw_args
        resolved_epic_id = _normalize_optional_text(getattr(source_args, "epic_id", None))
        resolved_queue = bool(getattr(source_args, "queue", False))
        resolved_yes = bool(getattr(source_args, "yes", False))
        resolved_reconcile = bool(getattr(source_args, "reconcile", False))
        resolved_select = _normalize_text(
            getattr(source_args, "select", _DEFAULT_STARTUP_SELECT),
            default=_DEFAULT_STARTUP_SELECT,
        )
        resolved_yolo = bool(getattr(source_args, "yolo", False))
        resolved_agent_bead_id = _normalize_optional_text(
            getattr(source_args, "agent_bead_id", None)
        )
        resolved_excluded = _normalize_string_tuple(
            getattr(source_args, "implicit_excluded_epic_ids", ())
        )
        resolved_iteration_token = _normalize_optional_text(
            getattr(source_args, "bounded_runtime_iteration_token", None)
        )
        resolved_restart_on_update = bool(getattr(source_args, "restart_on_update", False))
        resolved_startup_runtime = getattr(source_args, "startup_runtime", None)

    if epic_id is not _UNSET:
        resolved_epic_id = _normalize_optional_text(epic_id)
    if implicit_excluded_epic_ids is not _UNSET:
        resolved_excluded = _normalize_string_tuple(implicit_excluded_epic_ids)
    if bounded_runtime_iteration_token is not _UNSET:
        resolved_iteration_token = _normalize_optional_text(bounded_runtime_iteration_token)
    if restart_on_update is not _UNSET:
        resolved_restart_on_update = bool(restart_on_update)
    if startup_runtime is not _UNSET:
        resolved_startup_runtime = startup_runtime

    return WorkerIterationArgs(
        raw_args=source_args,
        epic_id=resolved_epic_id,
        queue=resolved_queue,
        yes=resolved_yes,
        reconcile=resolved_reconcile,
        select=resolved_select,
        yolo=resolved_yolo,
        agent_bead_id=resolved_agent_bead_id,
        implicit_excluded_epic_ids=resolved_excluded,
        bounded_runtime_iteration_token=resolved_iteration_token,
        restart_on_update=resolved_restart_on_update,
        startup_runtime=resolved_startup_runtime,
    )
