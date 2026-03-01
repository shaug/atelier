"""GC operations for label migration and normalization."""

from __future__ import annotations

from pathlib import Path

from .. import beads, lifecycle
from .common import (
    issue_labels,
    issue_sort_key,
    normalize_branch,
)
from .models import GcAction


def _resolve_changeset_status_for_migration(
    issue: dict[str, object],
) -> tuple[str | None, tuple[str, ...]]:
    if not lifecycle.is_work_issue(
        labels=issue_labels(issue),
        issue_type=lifecycle.issue_payload_type(issue),
    ):
        return None, ()
    current_status = lifecycle.normalize_status_value(issue.get("status"))
    target_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if target_status not in lifecycle.CANONICAL_LIFECYCLE_STATUSES:
        return None, ()
    if target_status == current_status:
        return None, ()
    if current_status is None:
        return (
            target_status,
            (f"status -> {target_status}: derive canonical status from legacy status aliases",),
        )
    return (
        target_status,
        (f"status {current_status} -> {target_status}: normalize lifecycle status",),
    )


def _resolve_epic_status_for_migration(
    issue: dict[str, object],
) -> tuple[str | None, tuple[str, ...]]:
    labels = issue_labels(issue)
    if "at:epic" not in labels:
        return None, ()
    current_status = lifecycle.normalize_status_value(issue.get("status"))
    target_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if target_status not in lifecycle.CANONICAL_LIFECYCLE_STATUSES:
        return None, ()
    if target_status == current_status:
        return None, ()
    if current_status is None:
        return (
            target_status,
            (f"status -> {target_status}: derive canonical status from legacy status aliases",),
        )
    return (
        target_status,
        (f"status {current_status} -> {target_status}: normalize legacy lifecycle status",),
    )


def collect_normalize_changeset_labels(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    actions: list[GcAction] = []
    issues = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    for issue in sorted(issues, key=issue_sort_key):
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        issue_id = issue_id.strip()
        status_target, status_reasons = _resolve_changeset_status_for_migration(issue)
        if status_target is None:
            continue
        status_value = status_target
        current_status = lifecycle.normalize_status_value(issue.get("status")) or "missing"
        details = [f"status: {current_status} -> {status_value}"]
        details.extend(status_reasons)

        def _apply_normalize(
            bead_id: str = issue_id,
            status_value: str = status_value,
        ) -> None:
            beads.run_bd_command(
                ["update", bead_id, "--status", status_value],
                beads_root=beads_root,
                cwd=repo_root,
            )

        actions.append(
            GcAction(
                description=f"Normalize lifecycle status for changeset {issue_id}",
                apply=_apply_normalize,
                details=tuple(details),
            )
        )
    return actions


def collect_remove_deprecated_label(
    *,
    label: str,
    detail: str,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    """Remove deprecated label; state is inferred from bead status or graph."""
    actions: list[GcAction] = []
    issues = beads.run_bd_json(
        ["list", "--label", label, "--all"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in sorted(issues, key=issue_sort_key):
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        issue_id = issue_id.strip()

        def _apply_remove(
            bead_id: str = issue_id,
            lbl: str = label,
        ) -> None:
            beads.run_bd_command(
                ["update", bead_id, "--remove-label", lbl],
                beads_root=beads_root,
                cwd=repo_root,
            )

        actions.append(
            GcAction(
                description=f"Remove deprecated {label} label from {issue_id}",
                apply=_apply_remove,
                details=(detail,),
            )
        )
    return actions


def collect_normalize_epic_labels(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    actions: list[GcAction] = []
    issues = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    for issue in sorted(issues, key=issue_sort_key):
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        issue_id = issue_id.strip()
        status_target, status_reasons = _resolve_epic_status_for_migration(issue)
        if status_target is None:
            continue
        status_value = status_target
        current_status = lifecycle.normalize_status_value(issue.get("status")) or "missing"
        details = [f"status: {current_status} -> {status_value}"]
        details.extend(status_reasons)

        def _apply_normalize(
            bead_id: str = issue_id,
            status_value: str = status_value,
        ) -> None:
            beads.run_bd_command(
                ["update", bead_id, "--status", status_value],
                beads_root=beads_root,
                cwd=repo_root,
            )

        actions.append(
            GcAction(
                description=f"Normalize lifecycle status for epic {issue_id}",
                details=tuple(details),
                apply=_apply_normalize,
            )
        )
    return actions


def collect_report_epic_identity_guardrails(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    """Report active top-level work that drifts from executable epic identity."""
    report = beads.epic_discovery_parity_report(
        beads_root=beads_root,
        cwd=repo_root,
    )
    actions: list[GcAction] = []
    if report.missing_executable_identity:
        details: list[str] = [
            (
                "active top-level work must keep executable epic identity "
                "(issue_type=epic + label at:epic)"
            )
        ]
        for violation in report.missing_executable_identity:
            labels = ", ".join(violation.labels) if violation.labels else "(none)"
            details.append(
                f"{violation.issue_id}: status={violation.status or 'missing'}, "
                f"type={violation.issue_type or 'missing'}, labels={labels}"
            )
            details.append(f"remediation: {violation.remediation_command}")
        actions.append(
            GcAction(
                description="Report active top-level work missing executable epic identity",
                details=tuple(details),
                apply=lambda: None,
                report_only=True,
            )
        )

    if report.missing_from_index:
        details = [
            "epic discovery index drift detected for executable top-level work:",
            ", ".join(report.missing_from_index),
            "remediation: run `bd prime`; if mismatch persists run "
            "`bd doctor --fix --yes` and rerun gc",
        ]
        actions.append(
            GcAction(
                description="Report executable top-level work missing from epic discovery index",
                details=tuple(details),
                apply=lambda: None,
                report_only=True,
            )
        )

    return actions
