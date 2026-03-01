from __future__ import annotations

import importlib.util
import subprocess
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


def test_render_tickets_section_renders_none_when_no_external_tickets() -> None:
    module = _load_script_module()
    issue = {"description": "scope: test only"}

    section = module.render_ticket_section(issue)

    assert "## Tickets" in section
    assert "- None" in section


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


def test_render_tickets_section_includes_explicit_github_refs() -> None:
    module = _load_script_module()
    issue = {
        "description": (
            "scope: test\nnotes: Addresses #310 and fixes https://github.com/org/repo/issues/311\n"
        )
    }

    section = module.render_ticket_section(issue)

    assert "## Tickets" in section
    assert "- Addresses #310" in section
    assert "- Fixes #311" in section


def test_render_tickets_section_ignores_numbered_prose_after_action_token() -> None:
    module = _load_script_module()
    issue = {
        "description": (
            "scope: test\n"
            "notes: Fixes rollout confusion by documenting Step #1 and Step #2.\n"
            "notes: Addresses #918 for tracking.\n"
        )
    }

    section = module.render_ticket_section(issue)

    assert "## Tickets" in section
    assert "- Addresses #918" in section
    assert "#1" not in section
    assert "#2" not in section


def test_load_issue_defaults_to_direct_mode(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='[{"id":"at-1","description":"scope: test"}]',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    issue = module.load_issue("at-1", beads_dir=tmp_path, repo_path=tmp_path)

    assert issue["id"] == "at-1"
    assert captured["command"] == [
        "bd",
        "--db",
        str(tmp_path / "beads.db"),
        "show",
        "at-1",
        "--json",
    ]
