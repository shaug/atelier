import datetime as dt

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


def test_render_changeset_pr_body_renders_none_when_no_ticket_links() -> None:
    issue = {"title": "Add validation for missing payloads"}
    fields = {"scope": "Add request payload validation."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" in body
    assert "- None" in body


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


def test_render_changeset_pr_body_adds_explicit_github_issue_references() -> None:
    issue = {
        "title": "Improve stale queue handling",
        "description": (
            "scope: tighten stale queue cleanup\n"
            "notes: Fixes #412 and Addresses https://github.com/acme/repo/issues/417\n"
        ),
    }
    fields = {"scope": "Tighten stale queue cleanup."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" in body
    assert "- Fixes #412" in body
    assert "- Addresses #417" in body


def test_render_changeset_pr_body_parses_oxford_comma_issue_references() -> None:
    issue = {
        "title": "Preserve all referenced tickets",
        "description": (
            "scope: keep linked references stable\nnotes: Fixes #701, #702, and #703\n"
        ),
    }
    fields = {"scope": "Preserve all referenced tickets."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" in body
    assert "- Fixes #701" in body
    assert "- Fixes #702" in body
    assert "- Fixes #703" in body


def test_render_changeset_pr_body_dedupes_and_prefers_fixes_action() -> None:
    issue = {
        "title": "Normalize export handling",
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"512","relation":"context"}]\n'
            "notes: Fixes #512\n"
        ),
    }
    fields = {"scope": "Normalize export handling."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert body.count("#512") == 1
    assert "- Fixes #512" in body


def test_render_changeset_pr_body_ignores_numbered_prose_after_action_token() -> None:
    issue = {
        "title": "Clarify rollout steps",
        "description": (
            "scope: tighten deploy docs\n"
            "notes: Fixes rollout confusion by documenting Step #1 and Step #2.\n"
            "notes: Addresses #901 for the tracking issue.\n"
        ),
    }
    fields = {"scope": "Clarify rollout documentation."}

    body = publish.render_changeset_pr_body(issue, fields=fields)

    assert "## Tickets" in body
    assert "- Addresses #901" in body
    assert "#1" not in body
    assert "#2" not in body


def test_render_pr_ticket_lines_marks_closed_external_issue_as_addresses() -> None:
    issue = {
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"371","relation":"primary","state":"closed",'
            '"state_updated_at":"2026-03-01T16:30:04Z","last_synced_at":"2026-03-01T16:30:04Z"}]'
        )
    }

    lines = publish.render_pr_ticket_lines(
        issue, now=dt.datetime(2026, 3, 1, 16, 55, tzinfo=dt.UTC)
    )

    assert lines == ["- Addresses #371"]


def test_render_pr_ticket_lines_fails_closed_for_stale_state_metadata() -> None:
    issue = {
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"371","relation":"primary","state":"open",'
            '"state_updated_at":"2026-03-01T15:22:33Z","last_synced_at":"2026-03-01T15:22:33Z"}]'
        )
    }

    lines = publish.render_pr_ticket_lines(
        issue, now=dt.datetime(2026, 3, 1, 16, 55, tzinfo=dt.UTC)
    )

    assert lines == ["- Addresses #371"]


def test_render_pr_ticket_lines_ignores_recent_last_synced_when_state_timestamp_is_stale() -> None:
    issue = {
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"371","relation":"primary","state":"open",'
            '"state_updated_at":"2026-03-01T15:22:33Z","last_synced_at":"2026-03-01T16:54:00Z"}]'
        )
    }

    lines = publish.render_pr_ticket_lines(
        issue, now=dt.datetime(2026, 3, 1, 16, 55, tzinfo=dt.UTC)
    )

    assert lines == ["- Addresses #371"]


def test_render_pr_ticket_lines_allows_fixes_for_fresh_state_metadata() -> None:
    issue = {
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"387","relation":"primary","state":"open",'
            '"state_updated_at":"2026-03-01T16:50:00Z","last_synced_at":"2026-03-01T16:50:00Z"}]'
        )
    }

    lines = publish.render_pr_ticket_lines(
        issue, now=dt.datetime(2026, 3, 1, 16, 55, tzinfo=dt.UTC)
    )

    assert lines == ["- Fixes #387"]


def test_render_pr_ticket_lines_does_not_upgrade_closed_ticket_from_explicit_clause() -> None:
    issue = {
        "description": (
            "external_tickets: "
            '[{"provider":"github","id":"371","relation":"primary","state":"open",'
            '"state_updated_at":"2026-03-01T15:22:33Z","last_synced_at":"2026-03-01T15:22:33Z"}]\n'
            "notes: Fixes #371\n"
        )
    }

    lines = publish.render_pr_ticket_lines(
        issue, now=dt.datetime(2026, 3, 1, 16, 55, tzinfo=dt.UTC)
    )

    assert lines == ["- Addresses #371"]
