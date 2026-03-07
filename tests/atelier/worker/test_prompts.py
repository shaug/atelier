from __future__ import annotations

from atelier.worker.prompts import worker_opening_prompt


def test_worker_opening_prompt_uses_status_metadata_wording() -> None:
    prompt = worker_opening_prompt(
        project_enlistment="/repo",
        workspace_branch="feature/test",
        epic_id="at-epic",
        changeset_id="at-epic.1",
        changeset_title="Update worker prompt text",
    )

    assert "update beads status/metadata for this changeset" in prompt
    assert "update beads state/labels for this changeset" not in prompt
    assert "implement only committable changeset artifacts" in prompt
    assert "run a north-star self-review" in prompt
    assert "north_star_review.<timestamp>" in prompt
    assert "Do not treat comment closure alone as completion" in prompt
    assert "planner owns non-commit orchestration" in prompt
    assert "Do not set status=closed while PR lifecycle is active" in prompt
    assert "Close only when PR is terminal (`merged`/`closed`)" in prompt
    assert "Do not commit/push/publish while unmet acceptance criteria remain" in prompt


def test_worker_opening_prompt_review_feedback_avoids_label_reset_guidance() -> None:
    prompt = worker_opening_prompt(
        project_enlistment="/repo",
        workspace_branch="feature/test",
        epic_id="at-epic",
        changeset_id="at-epic.1",
        changeset_title="Update worker prompt text",
        review_feedback=True,
    )

    assert (
        "Do not mark this changeset complete while review feedback remains unaddressed." in prompt
    )
    assert "Do not create local pr-* branches for temporary PR inspection." in prompt
    assert "refs/atelier/review/* refs and clean them up after use." in prompt
    assert (
        "Do not reset lifecycle labels to ready while feedback remains unaddressed." not in prompt
    )
