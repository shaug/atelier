from __future__ import annotations

import time

from atelier import planning_refinement


def _block(**fields: str) -> str:
    lines = ["planning_refinement.v1"]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def test_refinement_selects_newest_authoritative_valid_block() -> None:
    notes = "\n\n".join(
        (
            _block(
                authoritative="true",
                required="true",
                approval_status="approved",
                latest_verdict="READY",
                plan_edit_rounds_max="5",
                post_impl_review_rounds_max="8",
            ),
            _block(
                authoritative="true",
                required="true",
                approval_status="approved",
                latest_verdict="REVISED",
                plan_edit_rounds_max="3",
                post_impl_review_rounds_max="4",
            ),
        )
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)

    assert selected is not None
    assert selected.latest_verdict == "REVISED"
    assert selected.plan_edit_rounds_max == 3
    assert selected.post_impl_review_rounds_max == 4


def test_refinement_uses_newest_valid_block_when_no_authoritative() -> None:
    notes = "\n\n".join(
        (
            _block(required="true", approval_status="approved", latest_verdict="READY"),
            _block(required="false", approval_status="missing", latest_verdict="REVISED"),
        )
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)

    assert selected is not None
    assert selected.required is False
    assert selected.latest_verdict == "REVISED"


def test_refinement_rejects_unknown_verdict_token() -> None:
    notes = _block(
        authoritative="true",
        required="true",
        approval_status="approved",
        latest_verdict="NOT_READY",
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)
    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert selected is None
    assert gate.claimable is False
    assert gate.reason == "refinement_metadata_missing_or_malformed"


def test_refinement_requires_complete_approval_evidence_when_required() -> None:
    notes = _block(
        authoritative="true",
        required="true",
        approval_status="approved",
        latest_verdict="READY",
    )

    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert gate.required is True
    assert gate.claimable is False
    assert gate.reason == "refinement_approval_missing"


def test_refinement_requiredness_follows_selected_winning_record() -> None:
    notes = "\n\n".join(
        (
            _block(
                authoritative="true",
                required="true",
                approval_status="approved",
                approval_source="operator",
                approved_by="planner-user",
                approved_at="2026-03-29T12:00:00Z",
                latest_verdict="READY",
            ),
            _block(
                authoritative="true",
                required="false",
                approval_status="missing",
                latest_verdict="REVISED",
            ),
        )
    )

    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert gate.selected is not None
    assert gate.selected.required is False
    assert gate.required is False
    assert gate.claimable is True
    assert gate.reason is None


def test_refinement_malformed_newest_authoritative_fails_closed_when_required() -> None:
    notes = "\n\n".join(
        (
            _block(
                authoritative="true",
                required="false",
                approval_status="missing",
                latest_verdict="REVISED",
            ),
            _block(
                authoritative="true",
                required="true",
                approval_status="approved",
                approval_source="operator",
                approved_by="planner-user",
                approved_at="2026-03-29T12:00:00Z",
                latest_verdict="NOT_READY",
            ),
        )
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)
    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert selected is None
    assert gate.required is True
    assert gate.claimable is False
    assert gate.reason == "refinement_metadata_missing_or_malformed"


def test_refinement_rejects_non_iso_approval_timestamp() -> None:
    notes = _block(
        authoritative="true",
        required="true",
        approval_status="approved",
        approval_source="operator",
        approved_by="planner-user",
        approved_at="tomorrow-ish",
        latest_verdict="READY",
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)
    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert selected is None
    assert gate.required is True
    assert gate.claimable is False
    assert gate.reason == "refinement_metadata_missing_or_malformed"


def test_refinement_parser_ignores_trailing_non_refinement_note_text() -> None:
    notes = (
        _block(
            authoritative="true",
            required="true",
            approval_status="approved",
            approval_source="operator",
            approved_by="planner-user",
            approved_at="2026-03-29T12:00:00Z",
            latest_verdict="READY",
        )
        + "\n\n"
        + "Follow-up note from operator: keep scope narrow for execution."
    )

    blocks = planning_refinement.parse_refinement_blocks(notes)
    selected = planning_refinement.select_winning_refinement(blocks)
    gate = planning_refinement.evaluate_refinement_claim_gate(notes)

    assert selected is not None
    assert selected.latest_verdict == "READY"
    assert gate.required is True
    assert gate.claimable is True
    assert gate.reason is None


def test_refinement_parser_handles_large_note_payload_performance() -> None:
    notes = "\n\n".join(
        _block(
            authoritative="true" if index % 10 == 0 else "false",
            required="true" if index % 2 == 0 else "false",
            approval_status="approved",
            latest_verdict="READY",
        )
        for index in range(1000)
    )

    started_at = time.perf_counter()
    blocks = planning_refinement.parse_refinement_blocks(notes)
    elapsed_seconds = time.perf_counter() - started_at

    assert len(blocks) == 1000
    assert elapsed_seconds < 1.0
