from atelier.worker import publish


def test_normalized_markdown_bullets_strips_markers() -> None:
    value = "- first\n* second\nthird\n\n"
    assert publish.normalized_markdown_bullets(value) == ["first", "second", "third"]


def test_render_changeset_pr_body_uses_scope_and_acceptance_criteria() -> None:
    issue = {
        "title": "Fix BetterAuth pagination correctness",
        "acceptance_criteria": (
            "Pagination returns deterministic page windows.\n"
            "- Admin memberships are paged after merge/sort."
        ),
    }
    fields = {
        "scope": "Fix pagination correctness in adapter and tests.",
        "rationale": "Prevent empty/truncated pages for admins.",
    }

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Summary" in body
    assert "Fix pagination correctness in adapter and tests." in body
    assert "## Why" in body
    assert "## Acceptance Criteria" in body
    assert "- Pagination returns deterministic page windows." in body
