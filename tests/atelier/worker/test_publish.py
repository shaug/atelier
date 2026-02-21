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


def test_render_changeset_pr_body_omits_tickets_section_without_external_links() -> None:
    issue = {"title": "Add validation for missing payloads"}
    fields = {"scope": "Add request payload validation."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" not in body


def test_render_changeset_pr_body_adds_external_ticket_lines() -> None:
    issue = {
        "title": "Improve role update safety",
        "description": (
            "scope: Enforce explicit clear flow.\n"
            "external_tickets: "
            '[{"provider":"github","id":"211","relation":"primary"},'
            '{"provider":"linear","id":"ABC-1311","relation":"context"}]'
        ),
    }
    fields = {"scope": "Enforce explicit clear behavior."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" in body
    assert "- Fixes #211" in body
    assert "- Addresses ABC-1311" in body
