from __future__ import annotations

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

    blocks = planning_refinement.parse_refinement_blocks(notes)

    assert len(blocks) == 1000
