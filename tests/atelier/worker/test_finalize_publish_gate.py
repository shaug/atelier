from __future__ import annotations

from atelier.worker.finalize_publish_gate import validate_north_star_review_gate


def test_validate_north_star_review_gate_prefers_authoritative_complete_artifact() -> None:
    issue = {
        "acceptance_criteria": "1) First criterion.\n2) Second criterion.\n",
        "notes": (
            "north_star_review.2026-03-07T10:00:00Z:\n"
            "1) unmet_acceptance_criteria: AC2\n"
            "2) required_code_changes_per_criterion:\n"
            "- AC1: old mapping.\n"
            "3) implementation_summary:\n"
            "- Old note.\n"
            "4) completion_checklist:\n"
            "- AC1 satisfied by commit deadbee; files: old.py.\n"
            "north_star_review.2026-03-07T11:00:00Z:\n"
            "authoritative: true\n"
            "1) unmet_acceptance_criteria: none\n"
            "2) required_code_changes_per_criterion:\n"
            "- AC1: add the publish gate before outbound push.\n"
            "- AC2: emit explicit blocked diagnostics when evidence is missing.\n"
            "3) implementation_summary:\n"
            "- Added validator wiring in the finalize pipeline.\n"
            "4) completion_checklist:\n"
            "- AC1 satisfied by commit abc1234; files: src/atelier/worker/finalize_pipeline.py.\n"
            "- AC2 satisfied by verification: publish gate now blocks before push; "
            "files: tests/atelier/worker/test_finalize_publish_gate.py.\n"
        ),
    }

    result = validate_north_star_review_gate(issue)

    assert result.ok is True
    assert result.artifact_name == "north_star_review.2026-03-07T11:00:00Z"
    assert "2 acceptance criteria" in result.summary


def test_validate_north_star_review_gate_requires_note() -> None:
    issue = {
        "acceptance_criteria": "1) Only criterion.\n",
        "notes": "implementation_2026-03-07:\n- no north-star artifact yet.\n",
    }

    result = validate_north_star_review_gate(issue)

    assert result.ok is False
    assert result.artifact_name is None
    assert "north_star_review" in result.summary
    assert result.diagnostics == (
        "Missing required `north_star_review.<timestamp>:` note in the changeset bead.",
    )


def test_validate_north_star_review_gate_rejects_unmet_and_incomplete_checklist() -> None:
    issue = {
        "acceptance_criteria": "1) First criterion.\n2) Second criterion.\n",
        "notes": (
            "north_star_review.2026-03-07T12:00:00Z:\n"
            "1) unmet_acceptance_criteria: AC2 still open\n"
            "2) required_code_changes_per_criterion:\n"
            "- AC1: add the publish gate.\n"
            "3) implementation_summary:\n"
            "- Started the publish gate.\n"
            "4) completion_checklist:\n"
            "- AC1 satisfied by commit abc1234.\n"
        ),
    }

    result = validate_north_star_review_gate(issue)

    assert result.ok is False
    assert result.artifact_name == "north_star_review.2026-03-07T12:00:00Z"
    assert any("unmet_acceptance_criteria" in line for line in result.diagnostics)
    assert any("required_code_changes_per_criterion" in line for line in result.diagnostics)
    assert any("completion_checklist" in line and "AC2" in line for line in result.diagnostics)
