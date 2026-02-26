from atelier import lifecycle


def test_is_eligible_epic_status_accepts_core_active_states() -> None:
    assert lifecycle.is_eligible_epic_status("open", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("ready", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("in_progress", allow_hooked=False) is True
    assert lifecycle.is_eligible_epic_status("hooked", allow_hooked=False) is False
    assert lifecycle.is_eligible_epic_status("hooked", allow_hooked=True) is True


def test_normalized_labels_handles_non_list_and_none_entries() -> None:
    assert lifecycle.normalized_labels(None) == set()
    assert lifecycle.normalized_labels(["at:ready", None, " at:hooked "]) == {
        "at:ready",
        "at:hooked",
    }


def test_is_active_root_branch_owner_uses_status_and_labels() -> None:
    assert (
        lifecycle.is_active_root_branch_owner(
            status="hooked",
            labels={"at:epic", "at:ready"},
        )
        is True
    )
    assert (
        lifecycle.is_active_root_branch_owner(
            status="blocked",
            labels={"at:epic", "at:hooked"},
        )
        is True
    )
    assert (
        lifecycle.is_active_root_branch_owner(
            status="closed",
            labels={"at:epic", "at:ready", "at:hooked"},
        )
        is False
    )


def test_is_changeset_ready_accepts_ready_label() -> None:
    labels = {"at:changeset", "cs:ready"}
    assert lifecycle.is_changeset_ready("open", labels) is True


def test_is_changeset_ready_rejects_planned_blocked_or_terminal_labels() -> None:
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:planned"}) is False
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:blocked"}) is False
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:merged"}) is False
    assert lifecycle.is_changeset_ready("open", {"at:changeset", "cs:abandoned"}) is False


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


def test_canonical_lifecycle_status_maps_legacy_status_values() -> None:
    assert lifecycle.canonical_lifecycle_status("ready") == "open"
    assert lifecycle.canonical_lifecycle_status("planned") == "deferred"
    assert lifecycle.canonical_lifecycle_status("hooked") == "in_progress"
    assert lifecycle.canonical_lifecycle_status("done") == "closed"


def test_canonical_lifecycle_status_uses_legacy_label_hints() -> None:
    assert lifecycle.canonical_lifecycle_status(None, labels={"at:changeset", "cs:planned"}) == (
        "deferred"
    )
    assert lifecycle.canonical_lifecycle_status(None, labels={"at:changeset", "cs:ready"}) == (
        "open"
    )
    assert lifecycle.canonical_lifecycle_status(None, labels={"at:changeset", "cs:merged"}) == (
        "closed"
    )


def test_is_work_issue_excludes_explicit_non_work_types_and_labels() -> None:
    assert (
        lifecycle.is_work_issue(
            labels={"at:changeset", "at:message"},
            issue_type="task",
        )
        is False
    )
    assert lifecycle.is_work_issue(labels=set(), issue_type="message") is False
    assert lifecycle.is_work_issue(labels={"at:changeset"}, issue_type=None) is True


def test_infer_work_role_top_level_leaf_is_epic_and_changeset() -> None:
    role = lifecycle.infer_work_role(
        labels={"at:changeset"},
        issue_type="task",
        parent_id=None,
        has_work_children=False,
    )

    assert role.is_work is True
    assert role.is_epic is True
    assert role.is_changeset is True
    assert role.is_leaf is True


def test_infer_work_role_child_with_children_is_internal_work_node() -> None:
    role = lifecycle.infer_work_role(
        labels={"at:changeset"},
        issue_type="task",
        parent_id="at-epic",
        has_work_children=True,
    )

    assert role.is_work is True
    assert role.is_epic is False
    assert role.is_changeset is False
    assert role.is_leaf is False


def test_evaluate_runnable_leaf_requires_leaf_status_and_dependencies() -> None:
    blocked = lifecycle.evaluate_runnable_leaf(
        status="open",
        labels={"at:changeset"},
        issue_type="task",
        parent_id="at-epic",
        has_work_children=False,
        dependencies_satisfied=False,
    )
    assert blocked.runnable is False
    assert "dependencies-unsatisfied" in blocked.reasons

    deferred = lifecycle.evaluate_runnable_leaf(
        status="deferred",
        labels={"at:changeset"},
        issue_type="task",
        parent_id="at-epic",
        has_work_children=False,
        dependencies_satisfied=True,
    )
    assert deferred.runnable is False
    assert "status=deferred" in deferred.reasons

    runnable = lifecycle.evaluate_runnable_leaf(
        status="open",
        labels={"at:changeset"},
        issue_type="task",
        parent_id="at-epic",
        has_work_children=False,
        dependencies_satisfied=True,
    )
    assert runnable.runnable is True
    assert runnable.reasons == ()
