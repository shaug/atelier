"""Rendered prompt validation for refine-plan prompt assembly.

Provenance:
- Adapted from trycycle `orchestrator/prompt_builder/validate_rendered.py`
- Baseline import reference: trycycle base commit `8ea3981`.
"""

from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")
_TAG_RE_TEMPLATE = r"<{tag}>(?P<body>.*?)</{tag}>"


class ValidationError(RuntimeError):
    """Raised when a rendered prompt fails contract validation."""


def validate_rendered_prompt(
    prompt_text: str,
    *,
    required_nonempty_tags: list[str] | None = None,
    ignore_tags_for_placeholders: list[str] | None = None,
) -> None:
    """Validate rendered prompt completeness constraints."""
    placeholder_scan_text = _strip_tag_bodies(
        prompt_text,
        tags=ignore_tags_for_placeholders or [],
    )
    _validate_no_placeholders(placeholder_scan_text)
    for tag in required_nonempty_tags or []:
        _validate_nonempty_tag(prompt_text, tag)


def _strip_tag_bodies(prompt_text: str, *, tags: list[str]) -> str:
    stripped = prompt_text
    for tag in tags:
        _validate_tag_name(tag)
        pattern = re.compile(_TAG_RE_TEMPLATE.format(tag=re.escape(tag)), re.DOTALL)
        stripped = pattern.sub(f"<{tag}></{tag}>", stripped)
    return stripped


def _validate_no_placeholders(prompt_text: str) -> None:
    matches = sorted(set(PLACEHOLDER_RE.findall(prompt_text)))
    if matches:
        raise ValidationError(
            "rendered prompt still contains unsubstituted placeholders: " + ", ".join(matches)
        )


def _validate_nonempty_tag(prompt_text: str, tag: str) -> None:
    _validate_tag_name(tag)
    pattern = re.compile(_TAG_RE_TEMPLATE.format(tag=re.escape(tag)), re.DOTALL)
    match = pattern.search(prompt_text)
    if not match:
        raise ValidationError(f"rendered prompt is missing required <{tag}> block")
    if not match.group("body").strip():
        raise ValidationError(f"rendered prompt has empty <{tag}> block")


def _validate_tag_name(tag: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", tag):
        raise ValidationError(f"invalid tag name: {tag!r}")
