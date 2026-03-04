"""Implementation for the ``atelier doctor`` command."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from rich import box
from rich.console import Console
from rich.table import Table

from .. import (
    agent_home,
    beads,
    changeset_fields,
    config,
    lifecycle,
    prefix_migration_drift,
    prs,
    worktrees,
)
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}
_ACTIVE_HOOK_STALE_HOURS = 24.0
_STARTUP_BLOCKER_CODES = frozenset(
    {
        "prefix-migration-drift",
        "in-progress-epic-unassigned",
        "in-progress-epic-unhooked",
        "in-progress-assignee-hook-mismatch",
        "metadata-missing-root-branch",
        "metadata-missing-work-branch",
        "metadata-missing-epic-mapping",
        "metadata-missing-mapping-work-branch",
        "metadata-work-branch-conflict",
        "metadata-worktree-path-conflict",
        "metadata-root-branch-conflict",
        "metadata-mapping-root-branch-conflict",
    }
)


@dataclass(frozen=True)
class _ActiveHookBlocker:
    agent_id: str
    hook_bead: str
    session_state: str
    heartbeat_at: str | None


@dataclass(frozen=True)
class _AgentRuntime:
    agent_id: str
    hook_bead: str | None
    session_state: str
    heartbeat_at: str | None


@dataclass(frozen=True)
class _DoctorFinding:
    code: str
    summary: str
    remediation: str
    severity: str
    epic_id: str | None
    changeset_id: str | None
    details: dict[str, object]

    @property
    def startup_blocker(self) -> bool:
        if self.code == "prefix-migration-drift" and not bool(self.details.get("changed")):
            return False
        return self.code in _STARTUP_BLOCKER_CODES

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "summary": self.summary,
            "remediation": self.remediation,
            "severity": self.severity,
            "startup_blocker": self.startup_blocker,
            "details": dict(sorted(self.details.items(), key=lambda item: item[0])),
        }
        if self.epic_id:
            payload["epic_id"] = self.epic_id
        if self.changeset_id:
            payload["changeset_id"] = self.changeset_id
        return payload


@dataclass(frozen=True)
class _DoctorCheckFamily:
    check_id: str
    title: str
    description: str
    in_scope_changesets: int
    findings: tuple[_DoctorFinding, ...]

    @property
    def changesets_with_findings(self) -> int:
        return len({finding.changeset_id for finding in self.findings if finding.changeset_id})

    @property
    def startup_blockers(self) -> int:
        return sum(1 for finding in self.findings if finding.startup_blocker)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.check_id,
            "title": self.title,
            "description": self.description,
            "counts": {
                "in_scope_changesets": self.in_scope_changesets,
                "findings": len(self.findings),
                "changesets_with_findings": self.changesets_with_findings,
                "startup_blockers": self.startup_blockers,
            },
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class _DoctorContext:
    project_data_dir: Path
    epics_by_id: dict[str, dict[str, object]]
    changesets: list[dict[str, object]]
    changeset_to_epic: dict[str, str]
    fields_by_changeset: dict[str, dict[str, str]]
    mappings_by_epic: dict[str, worktrees.WorktreeMapping | None]


def doctor(args: object) -> None:
    """Run project health diagnostics with optional prefix-drift repair."""
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    fix = bool(getattr(args, "fix", False))
    force = bool(getattr(args, "force", False))
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    if fix and not force:
        blockers = _active_agent_hook_blockers(beads_root=beads_root, repo_root=repo_root)
        if blockers:
            die(_active_hook_blockers_message(blockers))

    origin = project_config.project.origin or project_config.project.repo_url
    repo_slug = prs.github_repo_slug(origin)
    actions = prefix_migration_drift.repair_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        apply=fix,
        repo_slug=repo_slug,
        git_path=git_path,
    )
    context = _collect_doctor_context(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    hook_map, agent_index = _collect_agent_runtime(beads_root=beads_root, repo_root=repo_root)
    checks = _build_check_families(
        context=context,
        actions=actions,
        hook_map=hook_map,
        agent_index=agent_index,
        fix=fix,
    )
    counts = _doctor_counts(context=context, checks=checks, actions=actions)
    normalization_required_changesets = sum(1 for action in actions if action.changed)
    rollback_guidance = _rollback_guidance(project_data_dir=project_data_dir, beads_root=beads_root)

    mode = "fix" if fix else "check"
    project_info = {
        "project_dir": str(project_root),
        "repo_root": str(repo_root),
        "beads_root": str(beads_root),
    }
    payload = {
        "scope": "project",
        "scope_description": (
            "project health report covering prefix drift, startup-blocking lineage, "
            "and in-progress ownership integrity"
        ),
        "mode": mode,
        "fix": fix,
        "project": project_info,
        "counts": counts,
        "prefix_normalization": {
            "required": normalization_required_changesets > 0,
            "required_changesets": normalization_required_changesets,
        },
        "check_contract": {
            "check_mode_mutates": False,
            "fix_mode_mutating_checks": ["prefix_migration_drift"],
            "read_only_checks": [
                "startup_blocking_lineage_consistency",
                "in_progress_integrity_signals",
            ],
        },
        "checks": {check.check_id: check.as_dict() for check in checks},
        # Backward-compatible key kept for existing consumers.
        "prefix_migration_drift": [action.as_dict() for action in actions],
    }
    if fix:
        payload["rollback_guidance"] = rollback_guidance
    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return
    _render_doctor(
        project_info=project_info,
        counts=counts,
        checks=checks,
        actions=actions,
        fix=fix,
        rollback_guidance=rollback_guidance if fix else None,
    )


def _doctor_counts(
    *,
    context: _DoctorContext,
    checks: tuple[_DoctorCheckFamily, ...],
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
) -> dict[str, int]:
    changed = sum(1 for action in actions if action.changed)
    applied = sum(1 for action in actions if action.applied and action.changed)

    status_counts: dict[str, int] = {}
    for issue in context.changesets:
        normalized = lifecycle.canonical_lifecycle_status(issue.get("status")) or "unknown"
        status_counts[normalized] = status_counts.get(normalized, 0) + 1

    counts: dict[str, int] = {
        "changesets_total": len(context.changesets),
        "changesets_in_progress": status_counts.get("in_progress", 0),
        "changesets_blocked": status_counts.get("blocked", 0),
        "changesets_drifted": len(actions),
        "changesets_changed": changed,
        "changesets_applied": applied,
        "check_families": len(checks),
        "check_families_with_findings": sum(1 for check in checks if check.findings),
        "findings_total": sum(len(check.findings) for check in checks),
        "startup_blockers": sum(check.startup_blockers for check in checks),
    }
    for check in checks:
        counts[f"{check.check_id}_findings"] = len(check.findings)
        counts[f"{check.check_id}_changesets"] = check.changesets_with_findings
    return counts


def _build_check_families(
    *,
    context: _DoctorContext,
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
    hook_map: Mapping[str, tuple[str, ...]],
    agent_index: Mapping[str, _AgentRuntime],
    fix: bool,
) -> tuple[_DoctorCheckFamily, ...]:
    return (
        _build_prefix_migration_check(context=context, actions=actions, fix=fix),
        _build_startup_lineage_check(context=context),
        _build_in_progress_integrity_check(
            context=context,
            hook_map=hook_map,
            agent_index=agent_index,
        ),
    )


def _build_prefix_migration_check(
    *,
    context: _DoctorContext,
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
    fix: bool,
) -> _DoctorCheckFamily:
    findings: list[_DoctorFinding] = []
    for action in sorted(actions, key=lambda item: (item.changeset_id, item.epic_id)):
        drift_summary = ", ".join(action.drift_classes) or "drift detected"
        findings.append(
            _DoctorFinding(
                code="prefix-migration-drift",
                summary=f"{action.changeset_id}: {drift_summary}",
                remediation=_prefix_drift_remediation(action, fix=fix),
                severity="error" if action.changed else "warning",
                epic_id=action.epic_id,
                changeset_id=action.changeset_id,
                details=action.as_dict(),
            )
        )
    return _DoctorCheckFamily(
        check_id="prefix_migration_drift",
        title="Prefix Migration Drift",
        description=(
            "Detects branch/worktree lineage drift introduced by prefix migration and "
            "reports canonical repair targets."
        ),
        in_scope_changesets=len(context.changesets),
        findings=tuple(findings),
    )


def _build_startup_lineage_check(*, context: _DoctorContext) -> _DoctorCheckFamily:
    findings: list[_DoctorFinding] = []
    in_scope = [
        issue
        for issue in context.changesets
        if (lifecycle.canonical_lifecycle_status(issue.get("status")) or "")
        in (*lifecycle.ACTIVE_LIFECYCLE_STATUSES, "blocked")
    ]
    for issue in sorted(in_scope, key=lambda item: str(item.get("id") or "")):
        changeset_id = _normalize_text(issue.get("id"))
        if changeset_id is None:
            continue
        lifecycle_status = lifecycle.canonical_lifecycle_status(issue.get("status")) or ""
        enforce_missing_metadata = lifecycle_status in {"in_progress", "blocked"}

        epic_id = context.changeset_to_epic.get(changeset_id, changeset_id)
        fields = context.fields_by_changeset.get(changeset_id, {})
        metadata_root = _normalize_text(fields.get("changeset.root_branch"))
        metadata_work = _normalize_text(fields.get("changeset.work_branch"))
        issue_worktree = _normalize_worktree_path(
            fields.get("worktree_path"),
            project_data_dir=context.project_data_dir,
        )

        epic_issue = context.epics_by_id.get(epic_id, {})
        epic_root = _normalize_text(beads.extract_workspace_root_branch(epic_issue))
        mapping = context.mappings_by_epic.get(epic_id)
        mapping_root = _normalize_text(mapping.root_branch if mapping else None)
        mapping_work = _normalize_text(mapping.changesets.get(changeset_id) if mapping else None)
        mapping_worktree = _normalize_worktree_path(
            mapping.changeset_worktrees.get(changeset_id) if mapping else None,
            project_data_dir=context.project_data_dir,
        )

        if enforce_missing_metadata and metadata_root is None:
            findings.append(
                _DoctorFinding(
                    code="metadata-missing-root-branch",
                    summary=f"{changeset_id} is missing changeset.root_branch.",
                    remediation=(
                        "Run worker startup to populate lineage metadata before continuing."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={},
                )
            )
        if enforce_missing_metadata and metadata_work is None:
            findings.append(
                _DoctorFinding(
                    code="metadata-missing-work-branch",
                    summary=f"{changeset_id} is missing changeset.work_branch.",
                    remediation=(
                        "Run worker startup to populate work-branch metadata before execution."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={},
                )
            )

        if mapping is None:
            if enforce_missing_metadata:
                findings.append(
                    _DoctorFinding(
                        code="metadata-missing-epic-mapping",
                        summary=f"Epic {epic_id} has no worktree mapping metadata.",
                        remediation=(
                            "Re-run worker startup for this epic to synthesize mapping metadata."
                        ),
                        severity="error",
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        details={"epic_id": epic_id},
                    )
                )
            continue

        if enforce_missing_metadata and changeset_id != epic_id and mapping_work is None:
            findings.append(
                _DoctorFinding(
                    code="metadata-missing-mapping-work-branch",
                    summary=f"{changeset_id} has no mapping work-branch entry.",
                    remediation=("Re-run worker startup to reconcile changeset mapping entries."),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={"epic_id": epic_id},
                )
            )

        if mapping_work and metadata_work and mapping_work != metadata_work:
            findings.append(
                _DoctorFinding(
                    code="metadata-work-branch-conflict",
                    summary=(
                        f"{changeset_id} metadata work branch {metadata_work!r} conflicts "
                        f"with mapping {mapping_work!r}."
                    ),
                    remediation=(
                        "Run `atelier doctor --fix` to resolve work-branch override conflicts."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={
                        "metadata_work_branch": metadata_work,
                        "mapping_work_branch": mapping_work,
                    },
                )
            )

        if mapping_worktree and issue_worktree and mapping_worktree != issue_worktree:
            findings.append(
                _DoctorFinding(
                    code="metadata-worktree-path-conflict",
                    summary=(
                        f"{changeset_id} metadata worktree path {issue_worktree!r} conflicts "
                        f"with mapping {mapping_worktree!r}."
                    ),
                    remediation=(
                        "Run `atelier doctor --fix` to reconcile worktree-path conflicts."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={
                        "metadata_worktree_path": issue_worktree,
                        "mapping_worktree_path": mapping_worktree,
                    },
                )
            )

        if epic_root and metadata_root and epic_root != metadata_root:
            findings.append(
                _DoctorFinding(
                    code="metadata-root-branch-conflict",
                    summary=(
                        f"{changeset_id} metadata root branch {metadata_root!r} conflicts "
                        f"with epic root {epic_root!r}."
                    ),
                    remediation=(
                        "Run `atelier doctor --fix` or rerun startup to reconcile lineage metadata."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={
                        "metadata_root_branch": metadata_root,
                        "epic_root_branch": epic_root,
                    },
                )
            )

        if mapping_root and metadata_root and mapping_root != metadata_root:
            findings.append(
                _DoctorFinding(
                    code="metadata-mapping-root-branch-conflict",
                    summary=(
                        f"{changeset_id} metadata root branch {metadata_root!r} conflicts "
                        f"with mapping root {mapping_root!r}."
                    ),
                    remediation=(
                        "Run `atelier doctor --fix` to align mapping and lineage root branches."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={
                        "metadata_root_branch": metadata_root,
                        "mapping_root_branch": mapping_root,
                    },
                )
            )

    return _DoctorCheckFamily(
        check_id="startup_blocking_lineage_consistency",
        title="Startup-Blocking Lineage Consistency",
        description=(
            "Detects startup-blocking lineage and mapping inconsistencies for "
            "in-progress/blocked changesets; open changesets are checked for conflicts only."
        ),
        in_scope_changesets=len(in_scope),
        findings=tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.changeset_id or "",
                    item.code,
                    item.epic_id or "",
                ),
            )
        ),
    )


def _build_in_progress_integrity_check(
    *,
    context: _DoctorContext,
    hook_map: Mapping[str, tuple[str, ...]],
    agent_index: Mapping[str, _AgentRuntime],
) -> _DoctorCheckFamily:
    findings: list[_DoctorFinding] = []
    in_scope = [
        issue
        for issue in context.changesets
        if lifecycle.canonical_lifecycle_status(issue.get("status")) == "in_progress"
    ]

    for issue in sorted(in_scope, key=lambda item: str(item.get("id") or "")):
        changeset_id = _normalize_text(issue.get("id"))
        if changeset_id is None:
            continue
        epic_id = context.changeset_to_epic.get(changeset_id, changeset_id)
        epic_issue = context.epics_by_id.get(epic_id, {})
        assignee = _normalize_assignee(epic_issue.get("assignee"))
        hooked_agents = tuple(sorted(hook_map.get(epic_id, ())))

        if assignee is None:
            findings.append(
                _DoctorFinding(
                    code="in-progress-epic-unassigned",
                    summary=(f"{changeset_id} is in_progress but epic {epic_id} has no assignee."),
                    remediation=(
                        f"Assign epic {epic_id} to the active worker before continuing startup."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={"epic_id": epic_id},
                )
            )

        if not hooked_agents:
            findings.append(
                _DoctorFinding(
                    code="in-progress-epic-unhooked",
                    summary=f"{changeset_id} is in_progress but epic {epic_id} has no active hook.",
                    remediation=(
                        f"Re-run worker startup to restore the agent hook for epic {epic_id}."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={"epic_id": epic_id},
                )
            )

        if assignee and hooked_agents and assignee not in hooked_agents:
            findings.append(
                _DoctorFinding(
                    code="in-progress-assignee-hook-mismatch",
                    summary=(
                        f"{changeset_id} is in_progress but epic assignee {assignee} "
                        f"is not among hooked agents ({', '.join(hooked_agents)})."
                    ),
                    remediation=(
                        "Reconcile epic assignee/hook ownership so the same worker owns both."
                    ),
                    severity="error",
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    details={
                        "epic_assignee": assignee,
                        "hooked_agents": list(hooked_agents),
                    },
                )
            )

        if assignee:
            assignee_runtime = agent_index.get(assignee)
            if assignee_runtime and assignee_runtime.session_state == "stale":
                findings.append(
                    _DoctorFinding(
                        code="in-progress-assignee-session-stale",
                        summary=(
                            f"{changeset_id} is in_progress but assignee {assignee} appears stale."
                        ),
                        remediation=(
                            "Reclaim stale ownership or restart the worker session and hook."
                        ),
                        severity="warning",
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        details={
                            "epic_assignee": assignee,
                            "session_state": assignee_runtime.session_state,
                            "heartbeat_at": assignee_runtime.heartbeat_at,
                        },
                    )
                )

    return _DoctorCheckFamily(
        check_id="in_progress_integrity_signals",
        title="In-Progress Integrity Signals",
        description=(
            "Checks whether in-progress changesets have aligned epic assignment, "
            "hook state, and live worker sessions."
        ),
        in_scope_changesets=len(in_scope),
        findings=tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.changeset_id or "",
                    item.code,
                    item.epic_id or "",
                ),
            )
        ),
    )


def _prefix_drift_remediation(
    action: prefix_migration_drift.PrefixMigrationRepairAction,
    *,
    fix: bool,
) -> str:
    notes: list[str] = []
    if action.changed:
        targets: list[str] = []
        if action.update_changeset_metadata:
            targets.append("changeset lineage")
        if action.update_changeset_worktree_path:
            targets.append("changeset worktree_path")
        if action.update_mapping:
            targets.append("mapping branch/worktree")
        target_summary = ", ".join(targets) if targets else "lineage metadata"
        if fix:
            notes.append(f"repair applied in fix mode; updated {target_summary}")
            notes.append("rerun `atelier doctor` to confirm zero prefix drift findings")
        else:
            notes.append(f"run `atelier doctor --fix` to update {target_summary}")
    else:
        notes.append("drift is non-actionable: canonical branch/worktree already aligned")
    if "work-branch-conflict" in action.drift_classes:
        notes.append("resolves startup work-branch override conflicts")
    if "worktree-path-conflict" in action.drift_classes:
        notes.append("converges worktree path to canonical branch-selected location")
    if "metadata-missing-mapping-work-branch" in action.drift_classes:
        notes.append("backfills missing mapping work-branch lineage")
    if "metadata-missing-mapping-worktree-path" in action.drift_classes:
        notes.append("backfills missing mapping worktree-path lineage")
    return "; ".join(notes)


def _collect_doctor_context(
    *,
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
) -> _DoctorContext:
    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    epics_by_id: dict[str, dict[str, object]] = {}
    mappings_by_epic: dict[str, worktrees.WorktreeMapping | None] = {}
    for issue in epics:
        epic_id = _normalize_text(issue.get("id"))
        if epic_id is None:
            continue
        epics_by_id[epic_id] = issue
        mappings_by_epic[epic_id] = worktrees.load_mapping(
            worktrees.mapping_path(project_data_dir, epic_id)
        )

    changesets: list[dict[str, object]] = []
    changeset_to_epic: dict[str, str] = {}
    seen_changesets: set[str] = set()

    for epic_id in sorted(epics_by_id):
        descendants = beads.list_descendant_changesets(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if descendants:
            for issue in descendants:
                changeset_id = _normalize_text(issue.get("id"))
                if changeset_id is None or changeset_id in seen_changesets:
                    continue
                seen_changesets.add(changeset_id)
                changesets.append(issue)
                changeset_to_epic[changeset_id] = epic_id
            continue

        work_children = beads.list_work_children(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if work_children:
            continue

        if epic_id in seen_changesets:
            continue
        seen_changesets.add(epic_id)
        changesets.append(epics_by_id[epic_id])
        changeset_to_epic[epic_id] = epic_id

    changesets = sorted(changesets, key=lambda issue: str(issue.get("id") or ""))
    fields_by_changeset: dict[str, dict[str, str]] = {}
    for issue in changesets:
        issue_id = _normalize_text(issue.get("id"))
        if issue_id is None:
            continue
        fields_by_changeset[issue_id] = changeset_fields.issue_fields(issue)

    return _DoctorContext(
        project_data_dir=project_data_dir,
        epics_by_id=epics_by_id,
        changesets=changesets,
        changeset_to_epic=changeset_to_epic,
        fields_by_changeset=fields_by_changeset,
        mappings_by_epic=mappings_by_epic,
    )


def _collect_agent_runtime(
    *,
    beads_root: Path,
    repo_root: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, _AgentRuntime]]:
    stale_delta = dt.timedelta(hours=_ACTIVE_HOOK_STALE_HOURS)
    now = dt.datetime.now(tz=dt.timezone.utc)
    hook_map: dict[str, set[str]] = {}
    agent_index: dict[str, _AgentRuntime] = {}

    issues = beads.run_bd_json(
        ["list", "--label", beads.issue_label("agent", beads_root=beads_root)],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = _normalize_text(fields.get("agent_id")) or _normalize_text(issue.get("title"))
        if agent_id is None:
            agent_id = _normalize_text(issue.get("id"))
        if agent_id is None:
            continue

        hook_bead = _agent_hook_for_issue_no_write(
            issue,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        heartbeat_at = (
            fields.get("heartbeat_at") if isinstance(fields.get("heartbeat_at"), str) else None
        )
        session_state = _agent_hook_session_state(
            agent_id,
            heartbeat_at=heartbeat_at,
            now=now,
            stale_delta=stale_delta,
        )
        runtime = _AgentRuntime(
            agent_id=agent_id,
            hook_bead=hook_bead,
            session_state=session_state,
            heartbeat_at=heartbeat_at,
        )
        agent_index[agent_id] = runtime
        if hook_bead:
            hook_map.setdefault(hook_bead, set()).add(agent_id)

    normalized_hook_map = {
        hook_bead: tuple(sorted(agent_ids))
        for hook_bead, agent_ids in sorted(hook_map.items(), key=lambda item: item[0])
    }
    return normalized_hook_map, agent_index


def _agent_hook_for_issue_no_write(
    issue: dict[str, object],
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    issue_id = _normalize_text(issue.get("id"))
    if issue_id:
        result = beads.run_bd_command(
            ["slot", "show", issue_id, "--json"],
            beads_root=beads_root,
            cwd=repo_root,
            allow_failure=True,
        )
        if result.returncode == 0:
            raw = result.stdout.strip() if result.stdout else ""
            if raw:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = None
                hook = _extract_hook_from_slot_payload(payload)
                if hook:
                    return hook

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return _normalize_text(fields.get("hook_bead"))


def _extract_hook_from_slot_payload(payload: object) -> str | None:
    if isinstance(payload, str):
        return _normalize_text(payload)
    if isinstance(payload, list):
        for item in payload:
            hook = _extract_hook_from_slot_payload(item)
            if hook:
                return hook
        return None
    if not isinstance(payload, dict):
        return None
    if "hook" in payload:
        return _extract_hook_from_slot_payload(payload.get("hook"))
    slots = payload.get("slots")
    if isinstance(slots, dict):
        return _extract_hook_from_slot_payload(slots.get("hook"))
    for key in ("id", "issue_id", "bead_id", "bead"):
        value = _normalize_text(payload.get(key))
        if value:
            return value
    return None


def _active_agent_hook_blockers(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[_ActiveHookBlocker]:
    blockers: list[_ActiveHookBlocker] = []
    _hook_map, agent_index = _collect_agent_runtime(beads_root=beads_root, repo_root=repo_root)
    for agent_id, runtime in sorted(agent_index.items(), key=lambda item: item[0]):
        if runtime.hook_bead is None:
            continue
        if runtime.session_state == "stale":
            continue
        blockers.append(
            _ActiveHookBlocker(
                agent_id=agent_id,
                hook_bead=runtime.hook_bead,
                session_state=runtime.session_state,
                heartbeat_at=runtime.heartbeat_at,
            )
        )
    return blockers


def _agent_hook_session_state(
    agent_id: str,
    *,
    heartbeat_at: str | None,
    now: dt.datetime,
    stale_delta: dt.timedelta,
) -> str:
    if agent_home.session_pid_from_agent_id(agent_id) is not None:
        return "live" if agent_home.is_session_agent_active(agent_id) else "stale"
    heartbeat = _parse_rfc3339(heartbeat_at)
    if heartbeat is None:
        return "unknown"
    age = now - heartbeat
    if age > stale_delta:
        return "stale"
    return "live"


def _parse_rfc3339(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _render_doctor(
    *,
    project_info: Mapping[str, str],
    counts: Mapping[str, int],
    checks: tuple[_DoctorCheckFamily, ...],
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
    fix: bool,
    rollback_guidance: Mapping[str, str] | None,
) -> None:
    console = Console()
    overview = Table(title="Project Doctor", box=box.SIMPLE, show_header=False)
    overview.add_column("Field", style="bold")
    overview.add_column("Value", overflow="fold")
    overview.add_row("Project dir", _display_value(project_info.get("project_dir")))
    overview.add_row("Repo root", _display_value(project_info.get("repo_root")))
    overview.add_row("Beads root", _display_value(project_info.get("beads_root")))
    overview.add_row("Mode", "fix" if fix else "check")
    overview.add_row("Scope", "multi-check health report (read-only unless `--fix`)")
    overview.add_row("Changesets", _display_value(counts.get("changesets_total")))
    overview.add_row("In-progress changesets", _display_value(counts.get("changesets_in_progress")))
    overview.add_row("Blocked changesets", _display_value(counts.get("changesets_blocked")))
    normalization_required_changesets = sum(1 for action in actions if action.changed)
    normalization_required = "yes" if normalization_required_changesets > 0 else "no"
    overview.add_row(
        "Normalization required",
        f"{normalization_required} ({normalization_required_changesets})",
    )
    overview.add_row("Findings", _display_value(counts.get("findings_total")))
    overview.add_row("Startup blockers", _display_value(counts.get("startup_blockers")))
    console.print(overview)

    summary = Table(title="Health Check Summary", box=box.SIMPLE)
    summary.add_column("Check", no_wrap=True)
    summary.add_column("Scope", overflow="fold")
    summary.add_column("In Scope", justify="right")
    summary.add_column("Findings", justify="right")
    summary.add_column("Startup Blockers", justify="right")
    for check in checks:
        summary.add_row(
            check.title,
            check.description,
            str(check.in_scope_changesets),
            str(len(check.findings)),
            str(check.startup_blockers),
        )
    console.print(summary)

    if not any(check.findings for check in checks):
        console.print("No health findings detected.")
        return

    for check in checks:
        if not check.findings:
            continue
        if check.check_id == "prefix_migration_drift":
            _render_prefix_drift_findings(console, actions)
            continue
        _render_check_findings(console, check)

    if not fix and any(action.changed for action in actions):
        console.print("Run `atelier doctor --fix` to apply prefix-migration drift repairs.")
    if fix and rollback_guidance:
        console.print("Rollback guidance:")
        console.print(f"- Inspect Beads DB path: {rollback_guidance['beads_inspect']}")
        console.print(f"- Backup Beads state: {rollback_guidance['beads_backup']}")
        console.print(f"- Backup mapping metadata: {rollback_guidance['mapping_backup']}")


def _render_prefix_drift_findings(
    console: Console,
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
) -> None:
    table = Table(title="Prefix Migration Drift Findings", box=box.SIMPLE)
    table.add_column("Changeset", no_wrap=True)
    table.add_column("Drift", overflow="fold")
    table.add_column("Canonical", overflow="fold")
    table.add_column("Worktree", overflow="fold")
    table.add_column("Action", overflow="fold")
    for action in sorted(actions, key=lambda item: (item.changeset_id, item.epic_id)):
        canonical = (
            f"root={action.canonical_root_branch}, "
            f"work={action.canonical_work_branch} ({action.work_branch_source})"
        )
        worktree = f"{action.canonical_worktree_path} ({action.worktree_path_source})"
        table.add_row(
            action.changeset_id,
            ", ".join(action.drift_classes),
            canonical,
            worktree,
            _action_summary(action),
        )
    console.print(table)


def _render_check_findings(console: Console, check: _DoctorCheckFamily) -> None:
    table = Table(title=f"{check.title} Findings", box=box.SIMPLE)
    table.add_column("Changeset", no_wrap=True)
    table.add_column("Code", no_wrap=True)
    table.add_column("Summary", overflow="fold")
    table.add_column("Remediation", overflow="fold")
    for finding in check.findings:
        table.add_row(
            finding.changeset_id or "-",
            finding.code,
            finding.summary,
            finding.remediation,
        )
    console.print(table)


def _action_summary(action: prefix_migration_drift.PrefixMigrationRepairAction) -> str:
    targets: list[str] = []
    if action.update_workspace_root_branch:
        targets.append("workspace.root_branch")
    if action.update_changeset_metadata:
        targets.append("changeset lineage metadata")
    if action.update_changeset_worktree_path:
        targets.append("changeset worktree_path metadata")
    if action.update_mapping:
        targets.append("worktree mapping")
    if not targets:
        return "no-op"
    if action.applied:
        return "updated " + ", ".join(targets)
    return "would update " + ", ".join(targets)


def _normalize_assignee(value: object) -> str | None:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, dict):
        for key in ("id", "name", "login"):
            normalized = _normalize_text(value.get(key))
            if normalized:
                return normalized
    return None


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _normalize_worktree_path(value: object, *, project_data_dir: Path) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(project_data_dir)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix().lstrip("./")


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def _rollback_guidance(*, project_data_dir: Path, beads_root: Path) -> dict[str, str]:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta_dir = project_data_dir / "worktrees" / ".meta"
    meta_backup = project_data_dir / "worktrees" / f".meta.backup-{timestamp}"
    beads_backup = beads_root.parent / f"{beads_root.name}.backup-{timestamp}"
    return {
        "beads_inspect": f'BEADS_DIR="{beads_root}" bd info --json',
        "beads_backup": f'cp -R "{beads_root}" "{beads_backup}"',
        "mapping_backup": f'cp -R "{meta_dir}" "{meta_backup}"',
    }


def _active_hook_blockers_message(blockers: list[_ActiveHookBlocker]) -> str:
    lines = [
        "refusing `atelier doctor --fix`: active agent hooks detected",
        "running with active workers can race metadata and mapping writes",
        "re-run after workers stop, or pass `--force` to override this safety gate",
    ]
    for blocker in blockers:
        heartbeat = blocker.heartbeat_at or "missing"
        lines.append(
            "- agent="
            f"{blocker.agent_id} hook={blocker.hook_bead} state={blocker.session_state} "
            f"heartbeat_at={heartbeat}"
        )
    return "\n".join(lines)
