"""Tests for gc.common."""

from pathlib import Path
from unittest.mock import patch

import atelier.gc.common as gc_common
from atelier.lib.beads import BeadsCommandError, IssueRecord, ShowIssueRequest


class _FakeBeadsClient:
    def __init__(
        self,
        *,
        record: IssueRecord | None = None,
        error: Exception | None = None,
    ) -> None:
        self.record = record
        self.error = error
        self.show_requests: list[ShowIssueRequest] = []

    def show(self, request: ShowIssueRequest) -> IssueRecord:
        self.show_requests.append(request)
        if self.error is not None:
            raise self.error
        if self.record is None:
            raise AssertionError("record was not configured")
        return self.record


def test_parse_rfc3339_accepts_iso_with_z() -> None:
    result = gc_common.parse_rfc3339("2026-01-15T12:00:00Z")
    assert result is not None
    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 15


def test_parse_rfc3339_returns_none_for_empty() -> None:
    assert gc_common.parse_rfc3339(None) is None
    assert gc_common.parse_rfc3339("") is None
    assert gc_common.parse_rfc3339("   ") is None


def test_normalize_branch_cleans_value() -> None:
    assert gc_common.normalize_branch("  feat/foo  ") == "feat/foo"
    assert gc_common.normalize_branch("null") is None
    assert gc_common.normalize_branch("") is None
    assert gc_common.normalize_branch(None) is None


def test_workspace_branch_from_labels_extracts_workspace_label() -> None:
    assert gc_common.workspace_branch_from_labels({"workspace:feat/foo"}) == "feat/foo"
    assert gc_common.workspace_branch_from_labels({"at:epic"}) is None


def test_coerce_float_parses_numeric_values() -> None:
    assert gc_common.coerce_float(1) == 1.0
    assert gc_common.coerce_float(1.5) == 1.5
    assert gc_common.coerce_float("2.5") == 2.5
    assert gc_common.coerce_float(None) is None
    assert gc_common.coerce_float("") is None
    assert gc_common.coerce_float("invalid") is None


def test_try_show_issue_returns_none_when_bd_show_fails() -> None:
    client = _FakeBeadsClient(
        error=BeadsCommandError(
            "bd command failed (1): bd show missing --json\n"
            'Error fetching missing: no issue found matching "missing"'
        )
    )
    with (
        patch("atelier.gc.common.build_sync_beads_client", return_value=client) as build_client,
        patch("atelier.gc.common.log_warning") as log_warning,
    ):
        result = gc_common.try_show_issue("missing", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert result is None
    build_client.assert_called_once_with(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    assert client.show_requests == [ShowIssueRequest(issue_id="missing")]
    log_warning.assert_called_once()


def test_try_show_issue_skips_placeholder_id_without_lookup() -> None:
    with (
        patch("atelier.gc.common.build_sync_beads_client") as build_client,
        patch("atelier.gc.common.log_warning") as log_warning,
    ):
        result = gc_common.try_show_issue(
            " null ",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            context="agent hook metadata for worker-1",
        )

    assert result is None
    build_client.assert_not_called()
    log_warning.assert_called_once_with(
        "gc ignored malformed placeholder Beads id ' null ' "
        "in agent hook metadata for worker-1; treating metadata as unresolved"
    )


def test_try_show_issue_returns_issue_payload_on_success() -> None:
    payload = {"id": "at-123", "title": "Issue", "status": "open", "labels": []}
    client = _FakeBeadsClient(record=IssueRecord.model_validate(payload))
    with patch("atelier.gc.common.build_sync_beads_client", return_value=client):
        result = gc_common.try_show_issue(" at-123 ", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert result is not None
    assert result.id == payload["id"]
    assert result.title == payload["title"]
    assert result.status == payload["status"]
    assert result.labels == tuple(payload["labels"])
    assert client.show_requests == [ShowIssueRequest(issue_id="at-123")]
