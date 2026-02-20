from atelier import lifecycle


def test_is_eligible_epic_status_accepts_core_active_states() -> None:
    assert lifecycle.is_eligible_epic_status("open", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("ready", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("in_progress", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("hooked", allow_hooked=False) is False
    assert lifecycle.is_eligible_epic_status("hooked", allow_hooked=True) is True


def test_is_changeset_ready_accepts_ready_label() -> None:
    labels = {"at:changeset", "cs:ready"}
    assert lifecycle.is_changeset_ready("open", labels) is True


def test_is_changeset_ready_rejects_planned_blocked_or_terminal_labels() -> None:
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:planned"}) is False
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:blocked"}) is False
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:merged"}) is False
    assert (
        lifecycle.is_changeset_ready("open", {"at:changeset", "cs:abandoned"}) is False
    )


def test_is_changeset_ready_rejects_closed_status() -> None:
    assert lifecycle.is_changeset_ready("closed", {"at:changeset"}) is False
    assert lifecycle.is_changeset_ready("done", {"at:changeset"}) is False


def test_is_changeset_ready_allows_open_and_in_progress_changesets() -> None:
    assert lifecycle.is_changeset_ready("open", {"at:changeset"}) is True
    assert lifecycle.is_changeset_ready("in_progress", {"at:changeset"}) is True
    assert lifecycle.is_changeset_ready("hooked", {"at:changeset"}) is True


def test_normalize_review_state_handles_invalid_values() -> None:
    assert lifecycle.normalize_review_state(None) is None
    assert lifecycle.normalize_review_state(" null ") is None
    assert lifecycle.normalize_review_state(" In-Review ") == "in-review"


def test_in_review_candidate_prefers_live_state() -> None:
    labels = {"at:changeset"}
    assert (
        lifecycle.is_changeset_in_review_candidate(
            labels=labels,
            status="open",
            live_state="in-review",
            stored_review_state=None,
        )
        is True
    )
    assert (
        lifecycle.is_changeset_in_review_candidate(
            labels=labels,
            status="open",
            live_state="pushed",
            stored_review_state="in-review",
        )
        is False
    )


def test_in_review_candidate_rejects_non_changesets_and_terminal_items() -> None:
    assert (
        lifecycle.is_changeset_in_review_candidate(
            labels={"at:epic"},
            status="open",
            live_state=None,
            stored_review_state="in-review",
        )
        is False
    )
    assert (
        lifecycle.is_changeset_in_review_candidate(
            labels={"at:changeset", "cs:merged"},
            status="open",
            live_state=None,
            stored_review_state="in-review",
        )
        is False
    )
    assert (
        lifecycle.is_changeset_in_review_candidate(
            labels={"at:changeset"},
            status="closed",
            live_state=None,
            stored_review_state="in-review",
        )
        is False
    )
