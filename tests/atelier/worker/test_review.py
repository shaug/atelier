import time
from pathlib import Path
from unittest.mock import patch

import pytest

from atelier import beads, prs
from atelier.worker import review


def test_select_review_feedback_changeset_picks_oldest_unseen() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/a\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
        {
            "id": "at-1.2",
            "labels": [],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/b\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
    ]

    def fake_lookup(repo: str, branch: str, *, refresh: bool = False) -> prs.GithubPrLookup:
        number = 11 if branch == "feat/a" else 22
        return prs.GithubPrLookup(
            outcome="found",
            payload={
                "number": number,
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": None,
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
            },
        )

    def fake_feedback(payload: dict[str, object] | None, *, repo: str) -> str | None:
        if not payload:
            return None
        return "2026-02-20T11:00:00Z" if payload.get("number") == 11 else "2026-02-20T10:30:00Z"

    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="review_test")
    }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch("atelier.worker.review.prs.lookup_github_pr_status", side_effect=fake_lookup),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            side_effect=fake_feedback,
        ),
        patch(
            "atelier.worker.review.prs.unresolved_review_thread_count",
            return_value=1,
        ),
    ):
        selection = review.select_review_feedback_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.epic_id == "at-1"
    assert selection.changeset_id == "at-1.2"


def test_select_review_feedback_changeset_tie_breaks_by_ids_after_parallel_scan() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/a\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
        {
            "id": "at-1.2",
            "labels": [],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/b\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
    ]
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="review_tie_break_test")
    }

    def fake_lookup(repo: str, branch: str, *, refresh: bool = False) -> prs.GithubPrLookup:
        del repo, refresh
        number = 11 if branch == "feat/a" else 22
        return prs.GithubPrLookup(
            outcome="found",
            payload={
                "number": number,
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": None,
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
            },
        )

    def fake_feedback(payload: dict[str, object] | None, *, repo: str) -> str | None:
        del repo
        if not payload:
            return None
        if payload.get("number") == 11:
            time.sleep(0.03)
        return "2026-02-20T11:00:00Z"

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch("atelier.worker.review.prs.lookup_github_pr_status", side_effect=fake_lookup),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            side_effect=fake_feedback,
        ),
        patch(
            "atelier.worker.review.prs.unresolved_review_thread_count",
            return_value=1,
        ),
    ):
        selection = review.select_review_feedback_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.changeset_id == "at-1.1"


def test_select_review_feedback_changeset_includes_standalone_epic_changeset() -> None:
    epic_issue = {
        "id": "at-standalone",
        "labels": ["at:epic"],
        "status": "in_progress",
        "description": "changeset.work_branch: feat/standalone\npr_state: in-review\n",
    }
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records([epic_issue], source="review_standalone")
    }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=[],
        ),
        patch(
            "atelier.worker.review.beads.list_work_children",
            return_value=[],
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch(
            "atelier.worker.review.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 31,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                    "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
                },
            ),
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch(
            "atelier.worker.review.prs.unresolved_review_thread_count",
            return_value=1,
        ),
    ):
        selection = review.select_review_feedback_changeset(
            epic_id="at-standalone",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.epic_id == "at-standalone"
    assert selection.changeset_id == "at-standalone"


def test_select_review_feedback_changeset_pr_160_closed_then_reopened_sequence() -> None:
    closed_issue = {
        "id": "at-1.60",
        "labels": [],
        "status": "closed",
        "description": (
            "changeset.work_branch: feat/pr-160\n"
            "pr_state: closed\n"
            "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
        ),
    }
    reopened_issue = {
        "id": "at-1.60",
        "labels": [],
        "status": "in_progress",
        "description": (
            "changeset.work_branch: feat/pr-160\n"
            "pr_state: pr-open\n"
            "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
        ),
    }
    pr_payload = {
        "number": 160,
        "state": "OPEN",
        "isDraft": False,
        "reviewDecision": None,
        "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
    }
    pr_lookup = prs.GithubPrLookup(outcome="found", payload=pr_payload)

    def select(issue: dict[str, object], *, source: str):
        with (
            patch(
                "atelier.worker.review.beads.list_descendant_changesets",
                return_value=[issue],
            ),
            patch(
                "atelier.worker.review.beads.BeadsClient.show_issue",
                return_value=beads.parse_issue_records([issue], source=source)[0],
            ),
            patch("atelier.worker.review.prs.lookup_github_pr_status", return_value=pr_lookup),
            patch(
                "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
                return_value="2026-02-20T11:00:00Z",
            ),
            patch(
                "atelier.worker.review.prs.unresolved_review_thread_count",
                return_value=1,
            ),
        ):
            return review.select_review_feedback_changeset(
                epic_id="at-1",
                repo_slug="org/repo",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )

    closed_selection = select(closed_issue, source="review_pr_160_closed")
    reopened_selection = select(reopened_issue, source="review_pr_160_reopened")

    assert closed_selection is None
    assert reopened_selection is not None
    assert reopened_selection.changeset_id == "at-1.60"


def test_select_global_review_feedback_changeset_retries_and_skips_failed_family() -> None:
    attempts: dict[tuple[str, ...], int] = {}

    def fake_read_query(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        key = tuple(args)
        attempts[key] = attempts.get(key, 0) + 1
        if key == ("list", "--label", "ts:epic", "--all", "--limit", "0"):
            return (
                [
                    {"id": "at-1", "labels": ["ts:epic"], "status": "open"},
                    {"id": "at-2", "labels": ["ts:epic"], "status": "in_progress"},
                ],
                None,
            )
        if key == ("list", "--label", "at:epic", "--all", "--limit", "0"):
            return (
                [
                    {"id": "at-1", "labels": ["at:epic"], "status": "open"},
                    {"id": "at-3", "labels": ["at:epic"], "status": "deferred"},
                ],
                None,
            )
        if key == ("list", "--parent", "at-1"):
            return (
                [
                    {
                        "id": "at-1.1",
                        "labels": [],
                        "parent_id": "at-1",
                        "issue_type": "task",
                        "status": "in_progress",
                        "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
                    }
                ],
                None,
            )
        if key == ("list", "--parent", "at-1.1"):
            return ([], None)
        if key == ("list", "--parent", "at-2"):
            return (
                [],
                ("command failed: bd list --parent at-2 --json (exit 1)\nstderr: TLS timeout"),
            )
        raise AssertionError(f"unexpected query: {args}")

    emitted: list[str] = []
    with (
        patch(
            "atelier.worker.review.beads.run_bd_json_read_only",
            side_effect=fake_read_query,
        ),
        patch(
            "atelier.worker.review.beads.issue_label_candidates",
            return_value=("at:epic", "ts:epic"),
        ),
        patch(
            "atelier.worker.review.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 42,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                    "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
                },
            ),
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch("atelier.worker.review.prs.unresolved_review_thread_count", return_value=1),
    ):
        selection = review.select_global_review_feedback_changeset(
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            resolve_epic_id_for_changeset=lambda _issue: (_ for _ in ()).throw(
                AssertionError("resolver should not be called during active global scan")
            ),
            emit_diagnostic=emitted.append,
        )

    assert selection is not None
    assert selection.epic_id == "at-1"
    assert selection.changeset_id == "at-1.1"
    assert attempts[("list", "--label", "ts:epic", "--all", "--limit", "0")] == 1
    assert attempts[("list", "--label", "at:epic", "--all", "--limit", "0")] == 1
    assert attempts[("list", "--parent", "at-1")] == 1
    assert attempts[("list", "--parent", "at-1.1")] == 1
    assert attempts[("list", "--parent", "at-2")] == 3
    assert ("list", "--parent", "at-3") not in attempts
    assert len(emitted) == 1
    assert "Startup stage global-review-feedback" in emitted[0]
    assert "bd list --parent at-2 --json" in emitted[0]
    assert "stderr: TLS timeout" in emitted[0]


def test_select_review_feedback_changeset_invalid_issue_payload_fails() -> None:
    issues = [{"status": "in_progress", "labels": []}]

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch("atelier.worker.review.beads.BeadsClient.show_issue", return_value=None),
    ):
        with pytest.raises(ValueError, match="invalid beads issue payload"):
            review.select_review_feedback_changeset(
                epic_id="at-1",
                repo_slug="org/repo",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )


def test_select_review_feedback_changeset_skips_when_no_unresolved_threads() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
        }
    ]
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="review_test")
    }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch(
            "atelier.worker.review.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 11,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                    "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
                },
            ),
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch(
            "atelier.worker.review.prs.unresolved_review_thread_count",
            return_value=0,
        ),
    ):
        selection = review.select_review_feedback_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is None


def test_select_conflicted_changeset_picks_oldest_conflict() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
            "updated_at": "2026-02-20T12:00:00Z",
        },
        {
            "id": "at-1.2",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/b\npr_state: in-review\n",
            "updated_at": "2026-02-20T11:00:00Z",
        },
    ]
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="test_select_conflicted")
    }

    def fake_pr_status(_repo: str, branch: str) -> dict[str, object] | None:
        if branch == "feat/a":
            return {"state": "OPEN", "isDraft": False, "mergeStateStatus": "CLEAN"}
        return {
            "state": "OPEN",
            "isDraft": False,
            "url": "https://github.com/org/repo/pull/2",
            "updatedAt": "2026-02-20T10:00:00Z",
            "mergeStateStatus": "DIRTY",
        }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch("atelier.worker.review.prs.read_github_pr_status", side_effect=fake_pr_status),
    ):
        selection = review.select_conflicted_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.epic_id == "at-1"
    assert selection.changeset_id == "at-1.2"
    assert selection.pr_url == "https://github.com/org/repo/pull/2"


def test_select_conflicted_changeset_tie_breaks_by_ids_after_parallel_scan() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
            "updated_at": "2026-02-20T10:00:00Z",
        },
        {
            "id": "at-1.2",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/b\npr_state: in-review\n",
            "updated_at": "2026-02-20T10:00:00Z",
        },
    ]
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="conflict_tie_break_test")
    }

    def fake_pr_status(_repo: str, branch: str) -> dict[str, object] | None:
        if branch == "feat/a":
            time.sleep(0.03)
        return {
            "state": "OPEN",
            "isDraft": False,
            "url": f"https://github.com/org/repo/pull/{1 if branch == 'feat/a' else 2}",
            "updatedAt": "2026-02-20T10:00:00Z",
            "mergeStateStatus": "DIRTY",
        }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch("atelier.worker.review.prs.read_github_pr_status", side_effect=fake_pr_status),
    ):
        selection = review.select_conflicted_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.changeset_id == "at-1.1"


def test_select_conflicted_changeset_includes_standalone_epic_changeset() -> None:
    epic_issue = {
        "id": "at-standalone",
        "labels": ["at:epic"],
        "status": "in_progress",
        "description": "changeset.work_branch: feat/standalone\npr_state: in-review\n",
        "updated_at": "2026-02-20T10:00:00Z",
    }
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records([epic_issue], source="conflict_standalone")
    }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=[],
        ),
        patch(
            "atelier.worker.review.beads.list_work_children",
            return_value=[],
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch(
            "atelier.worker.review.prs.read_github_pr_status",
            return_value={
                "state": "OPEN",
                "isDraft": False,
                "url": "https://github.com/org/repo/pull/44",
                "updatedAt": "2026-02-20T10:00:00Z",
                "mergeStateStatus": "DIRTY",
            },
        ),
    ):
        selection = review.select_conflicted_changeset(
            epic_id="at-standalone",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.epic_id == "at-standalone"
    assert selection.changeset_id == "at-standalone"
    assert selection.pr_url == "https://github.com/org/repo/pull/44"


def test_select_global_conflicted_changeset_uses_active_epic_scan() -> None:
    attempts: dict[tuple[str, ...], int] = {}

    def fake_read_query(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        key = tuple(args)
        attempts[key] = attempts.get(key, 0) + 1
        if key == ("list", "--label", "at:epic", "--all", "--limit", "0"):
            return (
                [
                    {"id": "at-1", "labels": ["at:epic"], "status": "open"},
                    {"id": "at-2", "labels": ["at:epic"], "status": "deferred"},
                ],
                None,
            )
        if key == ("list", "--parent", "at-1"):
            return (
                [
                    {
                        "id": "at-1.1",
                        "labels": [],
                        "parent_id": "at-1",
                        "issue_type": "task",
                        "status": "in_progress",
                        "updated_at": "2026-02-20T10:00:00Z",
                        "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
                    }
                ],
                None,
            )
        if key == ("list", "--parent", "at-1.1"):
            return ([], None)
        raise AssertionError(f"unexpected query: {args}")

    with (
        patch(
            "atelier.worker.review.beads.run_bd_json_read_only",
            side_effect=fake_read_query,
        ),
        patch(
            "atelier.worker.review.prs.read_github_pr_status",
            return_value={
                "state": "OPEN",
                "isDraft": False,
                "url": "https://github.com/org/repo/pull/44",
                "updatedAt": "2026-02-20T10:00:00Z",
                "mergeStateStatus": "DIRTY",
            },
        ),
    ):
        selection = review.select_global_conflicted_changeset(
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            resolve_epic_id_for_changeset=lambda _issue: (_ for _ in ()).throw(
                AssertionError("resolver should not be called during active global scan")
            ),
        )

    assert selection is not None
    assert selection.epic_id == "at-1"
    assert selection.changeset_id == "at-1.1"
    assert selection.pr_url == "https://github.com/org/repo/pull/44"
    assert attempts[("list", "--parent", "at-1.1")] == 1
    assert ("list", "--parent", "at-2") not in attempts


def test_select_global_startup_candidates_returns_conflict_and_feedback() -> None:
    attempts: dict[tuple[str, ...], int] = {}

    def fake_read_query(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        key = tuple(args)
        attempts[key] = attempts.get(key, 0) + 1
        if key == ("list", "--label", "at:epic", "--all", "--limit", "0"):
            return ([{"id": "at-1", "labels": ["at:epic"], "status": "open"}], None)
        if key == ("list", "--parent", "at-1"):
            return (
                [
                    {
                        "id": "at-1.1",
                        "labels": [],
                        "parent_id": "at-1",
                        "issue_type": "task",
                        "status": "in_progress",
                        "updated_at": "2026-02-20T10:00:00Z",
                        "description": (
                            "changeset.work_branch: feat/a\n"
                            "pr_state: in-review\n"
                            "review.last_feedback_seen_at: 2026-02-20T09:00:00Z\n"
                        ),
                    }
                ],
                None,
            )
        if key == ("list", "--parent", "at-1.1"):
            return ([], None)
        raise AssertionError(f"unexpected query: {args}")

    with (
        patch("atelier.worker.review.beads.run_bd_json_read_only", side_effect=fake_read_query),
        patch(
            "atelier.worker.review.beads.issue_label_candidates",
            return_value=("at:epic",),
        ),
        patch(
            "atelier.worker.review.prs.read_github_pr_status",
            return_value={
                "number": 55,
                "state": "OPEN",
                "isDraft": False,
                "url": "https://github.com/org/repo/pull/55",
                "updatedAt": "2026-02-20T10:00:00Z",
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
                "mergeStateStatus": "DIRTY",
            },
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch("atelier.worker.review.prs.unresolved_review_thread_count", return_value=1),
    ):
        selections = review.select_global_startup_candidates(
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selections.conflict is not None
    assert selections.conflict.changeset_id == "at-1.1"
    assert selections.feedback is not None
    assert selections.feedback.changeset_id == "at-1.1"
    assert attempts[("list", "--label", "at:epic", "--all", "--limit", "0")] == 1
    assert attempts[("list", "--parent", "at-1")] == 1
    assert attempts[("list", "--parent", "at-1.1")] == 1


def test_select_conflicted_changeset_skips_unknown_mergeability() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": [],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/a\npr_state: in-review\n",
        }
    ]
    record_by_id = {
        record.issue.id: record
        for record in beads.parse_issue_records(issues, source="test_select_conflicted_unknown")
    }

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.beads.BeadsClient.show_issue",
            side_effect=lambda issue_id, *, source: record_by_id.get(issue_id),
        ),
        patch(
            "atelier.worker.review.prs.read_github_pr_status",
            return_value={"state": "OPEN", "mergeStateStatus": "UNKNOWN"},
        ),
    ):
        selection = review.select_conflicted_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is None
