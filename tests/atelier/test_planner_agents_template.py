from __future__ import annotations

from pathlib import Path


def test_planner_agents_template_contains_core_sections() -> None:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "atelier"
        / "templates"
        / "AGENTS.planner.md.tmpl"
    )
    content = template_path.read_text(encoding="utf-8")
    assert "No Approval Step" in content
    assert "Skill Precedence" in content
    assert "Startup Behavior" in content
    assert "Bead Quality Standard" in content
    assert "Promotion" in content
    assert "External providers" in content
    assert "plan-changeset-guardrails" in content
    assert "plan-promote-epic" in content
    assert "planner-startup-check" in content
    assert "mail-send" in content
    assert "epic-list" in content
    assert "one child changeset" in content
    assert "decomposition rationale" in content
    assert "Do not claim or keep assignee ownership" in content
    assert "Planner owns operator decision handling" in content
    assert "Do not dispatch cleanup-only beads as worker executable work." in content
    assert "concrete issue, create or update a deferred bead immediately" in content
    assert "Create or update deferred beads immediately" in content
    assert "Capture first, then ask only for decisions" in content
