"""Worker publish/PR rendering helpers."""

from __future__ import annotations


def normalized_markdown_bullets(value: str) -> list[str]:
    """Normalize multiline text into plain bullet items."""
    items: list[str] = []
    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        elif line.startswith("* "):
            line = line[2:].strip()
        items.append(line)
    return items


def render_changeset_pr_body(
    issue: dict[str, object], *, fields: dict[str, str]
) -> str:
    """Render a user-facing PR body from bead fields."""
    summary = ""
    for key in ("scope", "intent", "summary", "rationale"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            summary = value.strip()
            break
    if not summary:
        summary = str(issue.get("title") or "Changeset implementation").strip()
    rationale = fields.get("rationale")
    rationale_text = rationale.strip() if isinstance(rationale, str) else ""
    acceptance_raw = issue.get("acceptance_criteria")
    acceptance_text = acceptance_raw.strip() if isinstance(acceptance_raw, str) else ""
    lines: list[str] = ["## Summary", summary]
    if rationale_text and rationale_text != summary:
        lines.extend(["", "## Why", rationale_text])
    if acceptance_text:
        lines.extend(["", "## Acceptance Criteria"])
        for item in normalized_markdown_bullets(acceptance_text):
            lines.append(f"- {item}")
    return "\n".join(lines).strip()
