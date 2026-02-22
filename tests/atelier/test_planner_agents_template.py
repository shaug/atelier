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
    assert "plan_changeset_guardrails" in content
    assert "plan_promote_epic" in content
    assert "planner_startup_check" in content
    assert "epic_list" in content
    assert "one child changeset" in content
    assert "decomposition rationale" in content
    assert "Do not claim or keep assignee ownership" in content
