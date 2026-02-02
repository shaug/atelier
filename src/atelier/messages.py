"""Message bead helpers for YAML frontmatter."""

from __future__ import annotations

from dataclasses import dataclass


FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class MessagePayload:
    metadata: dict[str, object]
    body: str


def _format_value(value: object) -> str:
    if value is None:
        return "null"
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
