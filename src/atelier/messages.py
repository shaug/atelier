"""Message bead helpers for YAML frontmatter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FRONTMATTER_DELIMITER = "---"
_RUNTIME_ROLE_ORDER: Final[tuple[str, ...]] = ("worker", "planner", "operator")
_RUNTIME_ROLES: Final[frozenset[str]] = frozenset(_RUNTIME_ROLE_ORDER)
_NEEDS_DECISION_SUBJECT_PREFIX: Final[str] = "NEEDS-DECISION:"


@dataclass(frozen=True)
class MessagePayload:
    metadata: dict[str, object]
    body: str


@dataclass(frozen=True)
class WorkThreadRouting:
    """Normalized work-thread routing metadata for one message issue.

    Attributes:
        issue_id: Message bead identifier, if present on the issue payload.
        title: Issue title/subject.
        body: Parsed message body without YAML frontmatter.
        thread_id: Thread bead id when the message is work-threaded.
        thread_target: Explicit thread target, usually ``epic`` or
            ``changeset`` when supplied by the sender.
        kind: Normalized message kind such as ``needs-decision``.
        audiences: Runtime roles explicitly or compatibly targeted by the
            message.
        blocking_roles: Runtime roles that the message should block until the
            message is processed.
    """

    issue_id: str | None
    title: str
    body: str
    thread_id: str | None
    thread_target: str | None
    kind: str | None
    audiences: tuple[str, ...]
    blocking_roles: tuple[str, ...]


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = ", ".join(str(item) for item in value)
        return f"[{items}]"
    return str(value)


def render_message(metadata: dict[str, object], body: str) -> str:
    """Render a message description with YAML frontmatter."""
    lines = [FRONTMATTER_DELIMITER]
    for key, value in metadata.items():
        lines.append(f"{key}: {_format_value(value)}")
    lines.append(FRONTMATTER_DELIMITER)
    lines.append("")
    body_text = body.rstrip("\n")
    if body_text:
        lines.append(body_text)
    return "\n".join(lines).rstrip("\n") + "\n"


def _parse_value(value: str) -> object:
    value = value.strip()
    if value.lower() == "null":
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip() for item in inner.split(",") if item.strip()]
    return value


def parse_message(description: str) -> MessagePayload:
    """Parse a message description into metadata and body."""
    raw = description.strip("\n")
    if not raw.startswith(FRONTMATTER_DELIMITER):
        return MessagePayload(metadata={}, body=description)
    lines = raw.splitlines()
    if len(lines) < 3:
        return MessagePayload(metadata={}, body=description)
    if lines[0].strip() != FRONTMATTER_DELIMITER:
        return MessagePayload(metadata={}, body=description)
    try:
        end_index = lines[1:].index(FRONTMATTER_DELIMITER) + 1
    except ValueError:
        return MessagePayload(metadata={}, body=description)
    metadata_lines = lines[1:end_index]
    metadata: dict[str, object] = {}
    for line in metadata_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        metadata[key] = _parse_value(value)
    body_lines = lines[end_index + 1 :]
    if body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]
    body = "\n".join(body_lines).rstrip("\n")
    return MessagePayload(metadata=metadata, body=body)


def _issue_title(issue: dict[str, object]) -> str:
    title = issue.get("title")
    if not isinstance(title, str):
        return ""
    return title.strip()


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    if not isinstance(description, str):
        return ""
    return description


def _issue_id(issue: dict[str, object]) -> str | None:
    issue_id = issue.get("id")
    if not isinstance(issue_id, str):
        return None
    normalized = issue_id.strip()
    return normalized or None


def _normalize_runtime_role(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "," in normalized:
        return None
    if "/" in normalized:
        parts = [part for part in normalized.split("/") if part]
        if not parts:
            return None
        normalized = parts[1] if parts[0] == "atelier" and len(parts) > 1 else parts[0]
    if normalized == "overseer":
        normalized = "operator"
    if normalized not in _RUNTIME_ROLES:
        return None
    return normalized


def _ordered_unique_roles(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for role in _RUNTIME_ROLE_ORDER:
        if role in values and role not in seen:
            seen.add(role)
            ordered.append(role)
    return tuple(ordered)


def _coerce_roles(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        candidates = list(value)
    elif isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    else:
        candidates = [value]
    roles = [
        normalized
        for candidate in candidates
        if (normalized := _normalize_runtime_role(candidate)) is not None
    ]
    return _ordered_unique_roles(roles)


def _message_thread_id(payload: MessagePayload) -> str | None:
    thread = payload.metadata.get("thread")
    if not isinstance(thread, str):
        return None
    normalized = thread.strip()
    return normalized or None


def _message_thread_target(payload: MessagePayload) -> str | None:
    raw_target = payload.metadata.get("thread_target")
    if not isinstance(raw_target, str):
        return None
    normalized = raw_target.strip().lower()
    return normalized or None


def _message_kind(payload: MessagePayload, *, title: str) -> str | None:
    for key in ("kind", "msg_type"):
        raw_value = payload.metadata.get(key)
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized:
                return normalized
    if title.startswith(_NEEDS_DECISION_SUBJECT_PREFIX):
        return "needs-decision"
    return None


def _message_audiences(issue: dict[str, object], payload: MessagePayload) -> tuple[str, ...]:
    explicit_roles = _coerce_roles(
        payload.metadata.get("audiences", payload.metadata.get("audience"))
    )
    if explicit_roles:
        return explicit_roles
    compatibility_roles = list(
        role
        for role in (
            _normalize_runtime_role(issue.get("assignee")),
            _normalize_runtime_role(payload.metadata.get("queue")),
        )
        if role is not None
    )
    return _ordered_unique_roles(compatibility_roles)


def _message_blocking_roles(
    issue: dict[str, object],
    payload: MessagePayload,
    *,
    thread_id: str | None,
    title: str,
    audiences: tuple[str, ...],
) -> tuple[str, ...]:
    explicit_roles = _coerce_roles(
        payload.metadata.get("blocking_roles", payload.metadata.get("blocking_for"))
    )
    if explicit_roles:
        return explicit_roles
    blocking_value = payload.metadata.get("blocking")
    if isinstance(blocking_value, bool):
        return audiences if blocking_value else ()
    if blocking_roles := _coerce_roles(blocking_value):
        return blocking_roles
    if title.startswith(_NEEDS_DECISION_SUBJECT_PREFIX):
        return audiences
    assignee_role = _normalize_runtime_role(issue.get("assignee"))
    if thread_id and assignee_role == "worker":
        return ("worker",)
    return ()


def work_thread_routing(issue: dict[str, object]) -> WorkThreadRouting:
    """Normalize work-thread routing metadata for a message bead.

    Args:
        issue: Message issue payload from Beads.

    Returns:
        Parsed routing metadata with compatibility fallbacks for legacy
        assignee/queue-based delivery.
    """

    payload = parse_message(_issue_description(issue))
    title = _issue_title(issue)
    thread_id = _message_thread_id(payload)
    audiences = _message_audiences(issue, payload)
    return WorkThreadRouting(
        issue_id=_issue_id(issue),
        title=title,
        body=payload.body,
        thread_id=thread_id,
        thread_target=_message_thread_target(payload),
        kind=_message_kind(payload, title=title),
        audiences=audiences,
        blocking_roles=_message_blocking_roles(
            issue,
            payload,
            thread_id=thread_id,
            title=title,
            audiences=audiences,
        ),
    )


def message_blocks_runtime(
    issue: dict[str, object],
    *,
    runtime_role: str,
    thread_ids: set[str] | None = None,
) -> bool:
    """Return whether a message blocks a specific runtime role.

    Args:
        issue: Message issue payload from Beads.
        runtime_role: Runtime role to evaluate: ``worker``, ``planner``, or
            ``operator``.
        thread_ids: Optional thread ids allowed to block this runtime. When
            omitted, any threaded message for the runtime is eligible.

    Returns:
        ``True`` when the message is threaded and blocks the requested role.
    """

    normalized_role = _normalize_runtime_role(runtime_role)
    if normalized_role is None:
        return False
    routing = work_thread_routing(issue)
    if routing.thread_id is None:
        return False
    if thread_ids is not None and routing.thread_id not in thread_ids:
        return False
    return normalized_role in routing.blocking_roles


def message_targets_runtime(
    issue: dict[str, object],
    *,
    runtime_role: str,
    thread_ids: set[str] | None = None,
) -> bool:
    """Return whether a threaded message targets a runtime role.

    Args:
        issue: Message issue payload from Beads.
        runtime_role: Runtime role to evaluate: ``worker``, ``planner``, or
            ``operator``.
        thread_ids: Optional thread ids allowed to match this runtime.

    Returns:
        ``True`` when the message is threaded and addressed to the runtime.
    """

    normalized_role = _normalize_runtime_role(runtime_role)
    if normalized_role is None:
        return False
    routing = work_thread_routing(issue)
    if routing.thread_id is None:
        return False
    if thread_ids is not None and routing.thread_id not in thread_ids:
        return False
    return normalized_role in routing.audiences


def render_work_thread_summary(issue: dict[str, object]) -> str:
    """Render a concise work-thread summary line for operator/agent prompts.

    Args:
        issue: Message issue payload from Beads.

    Returns:
        Compact summary text including thread, audience, kind, and body when
        present.
    """

    routing = work_thread_routing(issue)
    title = routing.title or "(untitled)"
    detail_parts: list[str] = []
    if routing.thread_id:
        target = routing.thread_target or "work"
        detail_parts.append(f"{target}={routing.thread_id}")
    if routing.kind:
        detail_parts.append(f"kind={routing.kind}")
    if routing.audiences:
        detail_parts.append(f"audience={','.join(routing.audiences)}")
    detail = f" ({'; '.join(detail_parts)})" if detail_parts else ""
    if routing.body:
        return f"{title}{detail}\n{routing.body}"
    return f"{title}{detail}"
