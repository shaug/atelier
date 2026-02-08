from __future__ import annotations

from pathlib import Path


def test_worker_agents_template_contains_core_sections() -> None:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "atelier"
        / "templates"
        / "AGENTS.worker.md.tmpl"
    )
    content = template_path.read_text(encoding="utf-8")
    assert "Worker Context" in content
    assert "Startup Behavior" in content
    assert "Execution Workflow" in content
    assert "Guardrails" in content
    assert "Finish" in content
