"""Message bead helpers for YAML frontmatter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

FRONTMATTER_DELIMITER = "---"
_CHANGESET_THREAD_PATTERN = re.compile(r".+\.\d+$")
_EPIC_THREAD_PATTERN = re.compile(r"[^.]+$")
_MESSAGE_KEY_ORDER = (
    "from",
    "delivery",
    "thread",
    "thread_kind",
    "audience",
    "kind",
    "blocking",
    "reply_to",
    "cc",
    "queue",
    "claimed_by",
    "claimed_at",
    "channel",
    "retention_days",
    "expires_at",
)
_RUNTIME_ROLE_ORDER: Final[tuple[str, ...]] = ("worker", "planner", "operator")
_RUNTIME_ROLES: Final[frozenset[str]] = frozenset(_RUNTIME_ROLE_ORDER)
_NEEDS_DECISION_SUBJECT_PREFIX: Final[str] = "NEEDS-DECISION:"

MessageDelivery = Literal["work-threaded", "agent-addressed"]
MessageThreadKind = Literal["changeset", "epic", "work"]


@dataclass(frozen=True)
class MessagePayload:
    """Parsed message description fields.

    Attributes:
        metadata: Raw YAML-frontmatter metadata parsed from the description.
        body: Markdown body content following the frontmatter block.
    """

    metadata: dict[str, object]
    body: str


@dataclass(frozen=True)
class MessageContract:
    """Normalized message contract used by worker/planner coordination.

    Attributes:
        metadata: Canonicalized frontmatter metadata preserving compatibility
            keys alongside normalized contract fields.
        body: Markdown body content following the frontmatter block.
        sender: Sender identity from the ``from`` field.
        delivery: Durable delivery mode for the message.
        thread_id: Work-thread target bead id when present.
        thread_kind: Explicit work-thread scope for ``thread_id``.
        audience: Intended role audiences for the message.
        kind: Semantic message kind such as ``notification`` or
            ``instruction``.
        blocking: Explicit blocking intent when provided.
        reply_to: Message id being replied to, if any.
    """

    metadata: dict[str, object]
    body: str
    sender: str | None
    delivery: MessageDelivery | None
    thread_id: str | None
    thread_kind: MessageThreadKind | None
    audience: tuple[str, ...]
    kind: str | None
    blocking: bool | None
    reply_to: str | None


@dataclass(frozen=True)
class WorkThreadRouting:
    """Normalized work-thread routing metadata for one message issue.

    Attributes:
        issue_id: Message bead identifier, if present on the issue payload.
        title: Issue title or subject.
        body: Parsed message body without YAML frontmatter.
        thread_id: Thread bead id when the message is work-threaded.
        thread_target: Explicit thread target, usually ``epic`` or
            ``changeset``.
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
    """Render a message description with YAML frontmatter.

    Args:
        metadata: Message frontmatter metadata to render.
        body: Markdown body content.

    Returns:
        Serialized message description including frontmatter and body.
    """

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
    """Parse a message description into metadata and body.

    Args:
        description: Serialized message description with optional frontmatter.

    Returns:
        Parsed metadata/body pair. If frontmatter is absent or malformed, the
        original description is returned as the body with empty metadata.
    """

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


def normalize_message_metadata(
    metadata: Mapping[str, object],
    *,
    assignee: str | None = None,
) -> dict[str, object]:
    """Normalize message metadata to the durable coordination contract.

    Args:
        metadata: Raw or partially-populated message metadata.
        assignee: Optional assignee used to infer compatibility-only routing.

    Returns:
        Canonicalized metadata preserving existing compatibility fields while
        adding normalized contract defaults where they can be derived
        unambiguously.
    """

    normalized = dict(metadata)
    thread_id = _clean_optional_string(normalized.get("thread"))
    if thread_id:
        normalized["thread"] = thread_id
    else:
        normalized.pop("thread", None)

    sender = _clean_optional_string(normalized.get("from"))
    if sender:
        normalized["from"] = sender
    else:
        normalized.pop("from", None)

    reply_to = _clean_optional_string(normalized.get("reply_to"))
    if reply_to:
        normalized["reply_to"] = reply_to
    else:
        normalized.pop("reply_to", None)

    kind = _clean_optional_string(normalized.get("kind"))
    if kind is None:
        kind = _clean_optional_string(normalized.get("msg_type"))
    if kind:
        normalized["kind"] = kind

    blocking = _coerce_optional_bool(normalized.get("blocking"))
    if blocking is not None:
        normalized["blocking"] = blocking

    audience = _normalize_audience(
        normalized.get("audience", normalized.get("audiences")),
        assignee=assignee,
        queue=normalized.get("queue"),
    )
    if audience:
        normalized["audience"] = list(audience)
    normalized.pop("audiences", None)

    thread_kind = _normalize_thread_kind(
        normalized.get("thread_kind", normalized.get("thread_target")),
        thread_id=thread_id,
    )
    if thread_kind:
        normalized["thread_kind"] = thread_kind
    normalized.pop("thread_target", None)

    delivery = _normalize_delivery(
        normalized.get("delivery"),
        thread_id=thread_id,
        assignee=assignee,
    )
    if delivery:
        normalized["delivery"] = delivery

    ordered: dict[str, object] = {}
    for key in _MESSAGE_KEY_ORDER:
        if key in normalized:
            ordered[key] = normalized[key]
    for key, value in normalized.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def build_message_contract(
    metadata: Mapping[str, object],
    *,
    body: str = "",
    assignee: str | None = None,
) -> MessageContract:
    """Build a normalized message contract from frontmatter metadata.

    Args:
        metadata: Raw message frontmatter metadata.
        body: Message body associated with the metadata.
        assignee: Optional assignee used for compatibility routing inference.

    Returns:
        Normalized contract fields used by later worker/planner logic.
    """

    normalized = normalize_message_metadata(metadata, assignee=assignee)
    audience_value = normalized.get("audience")
    audience = tuple(audience_value) if isinstance(audience_value, list) else ()
    return MessageContract(
        metadata=normalized,
        body=body,
        sender=_clean_optional_string(normalized.get("from")),
        delivery=_coerce_delivery(normalized.get("delivery")),
        thread_id=_clean_optional_string(normalized.get("thread")),
        thread_kind=_coerce_thread_kind(normalized.get("thread_kind")),
        audience=audience,
        kind=_clean_optional_string(normalized.get("kind")),
        blocking=_coerce_optional_bool(normalized.get("blocking")),
        reply_to=_clean_optional_string(normalized.get("reply_to")),
    )


def parse_message_contract(
    description: str,
    *,
    assignee: str | None = None,
) -> MessageContract:
    """Parse and normalize a full message description.

    Args:
        description: Serialized message description with optional frontmatter.
        assignee: Optional assignee used for compatibility routing inference.

    Returns:
        Normalized message contract for the parsed description.
    """

    payload = parse_message(description)
    return build_message_contract(payload.metadata, body=payload.body, assignee=assignee)


def _clean_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _coerce_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _normalize_runtime_role(value: object) -> str | None:
    normalized = _clean_optional_string(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if "," in lowered:
        return None
    if "/" in lowered:
        parts = [part for part in lowered.split("/") if part]
        if not parts:
            return None
        lowered = parts[1] if parts[0] == "atelier" and len(parts) > 1 else parts[0]
    if lowered == "overseer":
        lowered = "operator"
    if lowered not in _RUNTIME_ROLES:
        return None
    return lowered


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


def _normalize_audience(
    value: object,
    *,
    assignee: str | None,
    queue: object,
) -> tuple[str, ...]:
    roles = _coerce_roles(value)
    if roles:
        return roles
    queue_role = _normalize_runtime_role(queue)
    if queue_role is not None:
        return (queue_role,)
    assignee_role = _normalize_runtime_role(assignee)
    if assignee_role is not None:
        return (assignee_role,)
    return ()


def _normalize_thread_kind(
    value: object,
    *,
    thread_id: str | None,
) -> MessageThreadKind | None:
    normalized = _clean_optional_string(value)
    if normalized is not None:
        lowered = normalized.lower()
        if lowered == "changeset":
            return "changeset"
        if lowered == "epic":
            return "epic"
        if lowered == "work":
            return "work"
    if thread_id is None:
        return None
    if _CHANGESET_THREAD_PATTERN.fullmatch(thread_id):
        return "changeset"
    if _EPIC_THREAD_PATTERN.fullmatch(thread_id):
        return "epic"
    return "work"


def _normalize_delivery(
    value: object,
    *,
    thread_id: str | None,
    assignee: str | None,
) -> MessageDelivery | None:
    delivery = _coerce_delivery(value)
    if delivery is not None:
        return delivery
    if thread_id:
        return "work-threaded"
    if _clean_optional_string(assignee):
        return "agent-addressed"
    return None


def _coerce_delivery(value: object) -> MessageDelivery | None:
    normalized = _clean_optional_string(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered == "work-threaded":
        return "work-threaded"
    if lowered == "agent-addressed":
        return "agent-addressed"
    return None


def _coerce_thread_kind(value: object) -> MessageThreadKind | None:
    normalized = _clean_optional_string(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered == "changeset":
        return "changeset"
    if lowered == "epic":
        return "epic"
    if lowered == "work":
        return "work"
    return None


def _agent_role(agent_id: str | None) -> str | None:
    return _normalize_runtime_role(agent_id)


def _issue_title(issue: dict[str, object]) -> str:
    return _clean_optional_string(issue.get("title")) or ""


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    if not isinstance(description, str):
        return ""
    return description


def _issue_id(issue: dict[str, object]) -> str | None:
    return _clean_optional_string(issue.get("id"))


def _message_thread_target(contract: MessageContract) -> str | None:
    if contract.thread_kind is not None:
        return contract.thread_kind
    return _clean_optional_string(contract.metadata.get("thread_target"))


def _message_kind_from_contract(
    contract: MessageContract,
    *,
    title: str,
) -> str | None:
    if contract.kind:
        return contract.kind
    if title.startswith(_NEEDS_DECISION_SUBJECT_PREFIX):
        return "needs-decision"
    return None


def _message_blocking_roles(
    issue: dict[str, object],
    contract: MessageContract,
    *,
    title: str,
    audiences: tuple[str, ...],
) -> tuple[str, ...]:
    explicit_roles = _coerce_roles(
        contract.metadata.get("blocking_roles", contract.metadata.get("blocking_for"))
    )
    if explicit_roles:
        return explicit_roles
    blocking_value = contract.metadata.get("blocking")
    if isinstance(blocking_value, bool):
        return audiences if blocking_value else ()
    blocking_roles = _coerce_roles(blocking_value)
    if blocking_roles:
        return blocking_roles
    if title.startswith(_NEEDS_DECISION_SUBJECT_PREFIX):
        return audiences
    assignee_role = _normalize_runtime_role(issue.get("assignee"))
    if contract.thread_id and assignee_role == "worker":
        return ("worker",)
    return ()


def work_thread_routing(issue: dict[str, object]) -> WorkThreadRouting:
    """Normalize work-thread routing metadata for a message bead.

    Args:
        issue: Message issue payload from Beads.

    Returns:
        Parsed routing metadata with compatibility fallbacks for legacy
        assignee and queue-based delivery.
    """

    title = _issue_title(issue)
    contract = parse_message_contract(
        _issue_description(issue),
        assignee=_clean_optional_string(issue.get("assignee")),
    )
    audiences = contract.audience
    return WorkThreadRouting(
        issue_id=_issue_id(issue),
        title=title,
        body=contract.body,
        thread_id=contract.thread_id,
        thread_target=_message_thread_target(contract),
        kind=_message_kind_from_contract(contract, title=title),
        audiences=audiences,
        blocking_roles=_message_blocking_roles(
            issue,
            contract,
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
        runtime_role: Runtime role to evaluate.
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
        runtime_role: Runtime role to evaluate.
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
    """Render a concise work-thread summary line for prompts.

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
