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
