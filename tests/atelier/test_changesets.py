import atelier.changesets as changesets


def test_parse_review_metadata() -> None:
    description = "pr_url: https://example.com/pr/1\npr_state: open\n"
    meta = changesets.parse_review_metadata(description)
    assert meta.pr_url == "https://example.com/pr/1"
    assert meta.pr_state == "open"
    assert meta.pr_number is None


def test_apply_review_metadata_updates_description() -> None:
    description = "scope: test\n"
    meta = changesets.ReviewMetadata(
        pr_url="https://example.com/pr/2",
        pr_number="2",
        pr_state="review",
        review_owner="alice",
    )
    updated = changesets.apply_review_metadata(description, meta)
    assert "pr_url: https://example.com/pr/2" in updated
    assert "pr_number: 2" in updated
    assert "pr_state: review" in updated
    assert "review_owner: alice" in updated


def test_update_labels_for_pr_state_merged() -> None:
    labels = {"cs:ready", "cs:in_progress", "at:changeset"}
    updated = changesets.update_labels_for_pr_state(labels, "merged")
    assert "cs:merged" in updated
    assert "cs:abandoned" not in updated
    assert "cs:ready" not in updated
    assert "cs:planned" not in updated
    assert "cs:in_progress" not in updated
    assert "at:changeset" in updated


def test_update_labels_for_pr_state_abandoned() -> None:
    labels = {"cs:ready", "cs:in_progress"}
    updated = changesets.update_labels_for_pr_state(labels, "abandoned")
    assert "cs:abandoned" in updated
    assert "cs:merged" not in updated
    assert "cs:ready" not in updated
    assert "cs:in_progress" not in updated
