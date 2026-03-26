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
    assert "Single-Bead Contract" in content
    assert "Execution Workflow" in content
    assert "North-Star Review Loop" in content
    assert "PR Feedback Runs" in content
    assert "Messaging Rules" in content
    assert "Finish" in content
    assert "Do not look for more" in content
    assert "Update changeset status and metadata." in content
    assert "committable artifacts (code/config/docs/tests)" in content
    assert "Do not mutate sibling/unclaimed work-bead lifecycle state." in content
    assert "north_star_review.<timestamp>" in content
    assert "Do not treat comment closure alone as completion." in content
    bead_review = "In review-feedback mode, re-read the seeded epic and changeset beads first."
    fetch_feedback = "After the bead-first review, fetch open PR feedback and address it"
    assert bead_review in content
    assert fetch_feedback in content
    assert content.index(bead_review) < content.index(fetch_feedback)
    assert "Update changeset metadata and labels." not in content
    assert "do not set `status=closed`" in content
    assert "Set `status=closed` only when terminal proof exists" in content
    assert "Selected worker runtime profile: {{ worker_runtime_profile }}" in content
    assert "{{ worker_runtime_profile_contract }}" in content
