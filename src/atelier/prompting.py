"""Prompt template rendering helpers."""

from __future__ import annotations

from typing import Mapping


def render_template(template: str, variables: Mapping[str, str]) -> str:
    """Render a template using a simple {{ key }} substitution."""
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", value)
    return rendered
