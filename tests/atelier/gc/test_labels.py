"""Tests for gc.labels."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.gc.labels as gc_labels


def test_resolve_changeset_status_for_migration_maps_legacy_status_alias() -> None:
    issue = {"id": "at-123", "status": "ready", "labels": ["at:changeset"], "type": "task"}

    target, reasons = gc_labels._resolve_changeset_status_for_migration(issue)

    assert target == "open"
    assert any("normalize lifecycle status" in reason for reason in reasons)


def test_gc_normalize_changeset_labels_updates_legacy_status() -> None:
    issues = [
        {
            "id": "at-123",
            "status": "ready",
            "labels": ["at:changeset"],
            "type": "task",
        }
    ]
    calls: list[list[str]] = []

    def fake_list_all_changesets(*, beads_root: Path, cwd: Path, include_closed: bool) -> list:
        return issues

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.list_all_changesets", side_effect=fake_list_all_changesets),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_labels.collect_normalize_changeset_labels(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert len(actions) == 1
        actions[0].apply()

    assert calls == [["update", "at-123", "--status", "open"]]


def test_gc_normalize_changeset_labels_ignores_label_only_payloads() -> None:
    issues = [
        {
            "id": "at-123",
            "labels": ["at:changeset"],
        }
    ]

    def fake_list_all_changesets(*, beads_root: Path, cwd: Path, include_closed: bool) -> list:
        return issues

    with patch("atelier.beads.list_all_changesets", side_effect=fake_list_all_changesets):
        actions = gc_labels.collect_normalize_changeset_labels(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert actions == []


def test_gc_normalize_changeset_labels_orders_actions_deterministically() -> None:
    issues = [
        {"id": "at-200", "status": "ready", "labels": ["at:changeset"], "type": "task"},
        {"id": "at-100", "status": "ready", "labels": ["at:changeset"], "type": "task"},
    ]

    def fake_list_all_changesets(*, beads_root: Path, cwd: Path, include_closed: bool) -> list:
        return issues

    with patch("atelier.beads.list_all_changesets", side_effect=fake_list_all_changesets):
        actions = gc_labels.collect_normalize_changeset_labels(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert [action.description for action in actions] == [
        "Normalize lifecycle status for changeset at-100",
        "Normalize lifecycle status for changeset at-200",
    ]


def test_gc_normalize_epic_labels_updates_legacy_status() -> None:
    issues = [
        {
            "id": "at-epic",
            "status": "hooked",
            "labels": ["at:epic"],
        }
    ]
    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:4] == ["list", "--label", "at:epic", "--all"]:
            return issues
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_labels.collect_normalize_epic_labels(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert len(actions) == 1
        actions[0].apply()

    assert calls == [["update", "at-epic", "--status", "in_progress"]]


def test_gc_remove_deprecated_label_removes_at_changeset() -> None:
    issues = [
        {"id": "at-123", "labels": ["at:changeset"], "type": "task"},
    ]
    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:4] == ["list", "--label", "at:changeset", "--all"]:
            return issues
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_labels.collect_remove_deprecated_label(
            label="at:changeset",
            detail="changeset role inferred from graph",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert len(actions) == 1
        assert actions[0].description == "Remove deprecated at:changeset label from at-123"
        actions[0].apply()

    assert calls == [["update", "at-123", "--remove-label", "at:changeset"]]


def test_gc_remove_deprecated_label_orders_actions_deterministically() -> None:
    issues = [
        {"id": "at-200", "labels": ["at:changeset"], "type": "task"},
        {"id": "at-100", "labels": ["at:changeset"], "type": "task"},
    ]

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:4] == ["list", "--label", "at:changeset", "--all"]:
            return issues
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json):
        actions = gc_labels.collect_remove_deprecated_label(
            label="at:changeset",
            detail="changeset role inferred from graph",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert [action.description for action in actions] == [
        "Remove deprecated at:changeset label from at-100",
        "Remove deprecated at:changeset label from at-200",
    ]


def test_gc_remove_deprecated_label_removes_cs_labels() -> None:
    for label in ("cs:ready", "cs:in_progress", "cs:blocked", "cs:planned"):
        issues = [{"id": "at-1", "labels": [label, "at:epic"], "type": "task"}]
        calls: list[list[str]] = []

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if len(args) >= 4 and args[1:4] == ["--label", label, "--all"]:
                return issues
            return []

        def fake_run_bd_command(
            args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
        ) -> object:
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
            patch(
                "atelier.beads.run_bd_command",
                side_effect=fake_run_bd_command,
            ),
        ):
            actions = gc_labels.collect_remove_deprecated_label(
                label=label,
                detail="state inferred from status",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )
            assert len(actions) == 1
            assert actions[0].description == f"Remove deprecated {label} label from at-1"
            actions[0].apply()

        assert calls == [["update", "at-1", "--remove-label", label]]


def test_gc_report_epic_identity_guardrails_returns_report_only_actions() -> None:
    report = SimpleNamespace(
        missing_executable_identity=(
            SimpleNamespace(
                issue_id="at-missing",
                status="open",
                issue_type="epic",
                labels=(),
                remediation_command="bd update at-missing --type epic --add-label at:epic",
            ),
        ),
        missing_from_index=("at-indexed",),
    )

    with patch("atelier.beads.epic_discovery_parity_report", return_value=report):
        actions = gc_labels.collect_report_epic_identity_guardrails(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert len(actions) == 2
    assert all(action.report_only for action in actions)
    assert actions[0].description == "Report active top-level work missing executable epic identity"
    assert any(
        "remediation: bd update at-missing --type epic --add-label at:epic" in d
        for d in actions[0].details
    )
    assert (
        actions[1].description
        == "Report executable top-level work missing from epic discovery index"
    )
    assert any("at-indexed" in d for d in actions[1].details)


def test_gc_report_epic_identity_guardrails_noop_when_in_parity() -> None:
    report = SimpleNamespace(
        missing_executable_identity=(),
        missing_from_index=(),
    )

    with patch("atelier.beads.epic_discovery_parity_report", return_value=report):
        actions = gc_labels.collect_report_epic_identity_guardrails(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert actions == []
