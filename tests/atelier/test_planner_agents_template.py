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
    assert "plan-refined-deliberation" in content
    assert "plan-promote-epic" in content
    assert "planner-startup-check" in content
    assert "mail-send" in content
    assert "epic-list" in content
    assert "one child changeset" in content
    assert "decomposition rationale" in content
    assert "full epic contract and full child changeset contract details" in content
    assert "deterministic order" in content
    assert "dependencies, and" in content
    assert "related-context references" in content
    assert "show that gap explicitly" in content
    assert "operator clarification" in content
    assert 'non-goals ("what' in content
    assert "Do not ask for promotion while ambiguity remains." in content
    assert "Do not claim or keep assignee ownership" in content
    assert "check_issue_ownership.py" in content
    assert "do not infer executable ownership from raw" in content
    assert "Planner owns operator decision handling" in content
    assert "Planner/operator also own policy decisions" in content
    assert "lifecycle vocabulary, store" in content
    assert "backend normalization whenever more than one plausible public" in content
    assert "Workers implement the selected contract." in content
    assert "must not invent policy during" in content
    assert "Policy and boundary decisions:" in content
    assert "unsupported lifecycle status values" in content
    assert "maps them to canonical lifecycle terms" in content
    assert "legacy backend data leaks across the store boundary" in content
    assert "normalizes it, preserves it behind an adapter" in content
    assert "review feedback asks a worker to choose lifecycle semantics" in content
    assert "Preserve worker autonomy for implementation details" in content
    assert "Do not dispatch cleanup-only beads as worker executable work." in content
    assert "intent, rationale, non-goals, constraints, edge" in content
    assert "related-context links" in content
    assert "done definition" in content
    assert "`related_context:`" in content
    assert "`done_definition:`" in content
    assert "Use concrete wording instead of placeholders." in content
    assert "Acceptance criterion example:" in content
    assert "concrete issue, create or update a deferred bead immediately" in content
    assert "Create or update deferred beads immediately" in content
    assert "Capture first, then ask only for decisions" in content
    assert "Before task decomposition, run a strategy challenge:" in content
    assert "solving the right problem" in content
    assert "low bar for changing direction" in content
    assert "high bar for stopping to ask the user" in content
    assert "fundamental conflict between requirements and reality" in content
    assert "real risk of harm if you guess" in content
    assert "document the decision and rationale on the" in content
    assert "execution.strategy: refined" in content
    assert "planning.contract_json" in content
    assert "planning.stage: planning_in_review" in content
    assert "planning.stage: approved" in content
    assert "fail closed" in content
