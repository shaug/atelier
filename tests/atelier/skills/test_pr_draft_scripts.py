from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "pr-draft"
        / "scripts"
        / "render_tickets_section.py"
    )
    spec = importlib.util.spec_from_file_location("render_tickets_section", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_tickets_section_omits_when_no_external_tickets() -> None:
    module = _load_script_module()
    issue = {"description": "scope: test only"}

    section = module.render_ticket_section(issue)

    assert section == ""


def test_render_tickets_section_formats_fixes_and_addresses() -> None:
    module = _load_script_module()
    issue = {
        "description": (
            "scope: test\n"
            "external_tickets: "
            '[{"provider":"github","id":"204","relation":"primary"},'
            '{"provider":"linear","id":"ABC-181","relation":"context"}]'
        )
    }

    section = module.render_ticket_section(issue)

    assert "## Tickets" in section
    assert "- Fixes #204" in section
    assert "- Addresses ABC-181" in section
