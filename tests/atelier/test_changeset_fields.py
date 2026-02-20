from atelier import changeset_fields


def test_changeset_fields_extract_core_values() -> None:
    issue = {
        "description": (
            "changeset.work_branch: feat/work\n"
            "changeset.root_branch: feat/root\n"
            "pr_url: https://example.test/pr/1\n"
            "pr_state: In-Review\n"
        )
    }
    assert changeset_fields.work_branch(issue) == "feat/work"
    assert changeset_fields.root_branch(issue) == "feat/root"
    assert changeset_fields.pr_url(issue) == "https://example.test/pr/1"
    assert changeset_fields.review_state(issue) == "in-review"


def test_changeset_fields_normalizes_empty_and_null_values() -> None:
    issue = {
        "description": (
            "changeset.work_branch: null\nchangeset.root_branch:\npr_url:   \n"
        )
    }
    assert changeset_fields.work_branch(issue) is None
    assert changeset_fields.root_branch(issue) is None
    assert changeset_fields.pr_url(issue) is None
