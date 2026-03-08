"""Message bead helpers for YAML frontmatter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

FRONTMATTER_DELIMITER = "---"
_CHANGESET_THREAD_PATTERN = re.compile(r".+\.\d+$")
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
        sender: Sender identity from the `from` field.
        delivery: Durable delivery mode for the message.
        thread_id: Work-thread target bead id when present.
        thread_kind: Explicit work-thread scope for `thread_id`.
        audience: Intended role audiences for the message.
        kind: Semantic message kind such as `notification` or `instruction`.
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
        normalized.get("audience"),
        assignee=assignee,
        queue=normalized.get("queue"),
    )
    if audience:
        normalized["audience"] = list(audience)

    thread_kind = _normalize_thread_kind(normalized.get("thread_kind"), thread_id=thread_id)
    if thread_kind:
        normalized["thread_kind"] = thread_kind

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


def _normalize_audience(
    value: object,
    *,
    assignee: str | None,
    queue: object,
) -> tuple[str, ...]:
    if isinstance(value, str):
        candidate = value.strip().lower()
        return (candidate,) if candidate else ()
    if isinstance(value, list):
        normalized = tuple(
            candidate for item in value if (candidate := _clean_optional_string(item)) is not None
        )
        return tuple(candidate.lower() for candidate in normalized)
    queue_name = _clean_optional_string(queue)
    if queue_name == "planner":
        return ("planner",)
    if queue_name in {"overseer", "operator"}:
        return ("operator",)
    role = _agent_role(assignee)
    if role in {"worker", "planner", "operator"}:
        return (role,)
    return ()


def _normalize_thread_kind(value: object, *, thread_id: str | None) -> MessageThreadKind | None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "changeset":
            return "changeset"
        if normalized == "epic":
            return "epic"
        if normalized == "work":
            return "work"
    if thread_id is None:
        return None
    if _CHANGESET_THREAD_PATTERN.fullmatch(thread_id):
        return "changeset"
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
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "work-threaded":
        return "work-threaded"
    if normalized == "agent-addressed":
        return "agent-addressed"
    return None


def _coerce_thread_kind(value: object) -> MessageThreadKind | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "changeset":
        return "changeset"
    if normalized == "epic":
        return "epic"
    if normalized == "work":
        return "work"
    return None


def _agent_role(agent_id: str | None) -> str | None:
    identity = _clean_optional_string(agent_id)
    if identity is None:
        return None
    parts = [part for part in identity.split("/") if part]
    if not parts:
        return None
    if parts[0] == "atelier" and len(parts) >= 2:
        return parts[1].strip().lower() or None
    return parts[0].strip().lower() or None
