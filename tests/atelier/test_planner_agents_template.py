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
    assert "Startup Behavior" in content
    assert "Bead Quality Standard" in content
    assert "Promotion" in content
