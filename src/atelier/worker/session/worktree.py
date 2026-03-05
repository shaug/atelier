"""Worker session worktree preparation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import beads, changeset_fields, git, prefix_migration_drift, prs, worktrees


@dataclass(frozen=True)
class WorktreePreparation:
    epic_worktree_path: Path | None
    changeset_worktree_path: Path | None
    branch: str | None


@dataclass(frozen=True)
class WorktreePreparationContext:
    dry_run: bool
    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    selected_epic: str
    changeset_id: str
    root_branch_value: str
    changeset_parent_branch: str
    allow_parent_branch_override: bool
    git_path: str | None
    epic_parent_branch: str = ""


class WorktreePreparationControl(Protocol):
    """Runtime logging hooks used by worktree preparation."""

    def say(self, message: str) -> None: ...

    def dry_run_log(self, message: str) -> None: ...


_BLOCKING_PREFIX_DRIFT_CLASSES = frozenset(
    {
        "metadata-read-failure",
        "root-branch-conflict",
        "work-branch-conflict",
        "worktree-path-conflict",
    }
)


def _normalize_drift_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return normalized
    return str(value)


def _format_drift_values(raw: object) -> str:
    values = raw if isinstance(raw, dict) else {}
    normalized: dict[str, str | None] = {}
    for key, value in values.items():
        normalized[str(key)] = _normalize_drift_value(value)
    return json.dumps(dict(sorted(normalized.items())), sort_keys=True, separators=(",", ":"))


def _startup_worktree_preflight(
    *,
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
    selected_epic: str,
    changeset_id: str,
    root_branch_value: str,
    changeset_parent_branch: str,
    allow_parent_branch_override: bool,
    git_path: str | None,
) -> None:
    """Fail closed when startup detects blocking prefix-migration drift."""
    repo_slug = prs.github_repo_slug(git.git_origin_url(repo_root))
    target_changesets = {selected_epic.strip(), changeset_id.strip()}
    target_changesets.discard("")
    if not target_changesets:
        return

    planned_actions = prefix_migration_drift.repair_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        apply=False,
        repo_slug=repo_slug,
        git_path=git_path,
        target_epic_id=selected_epic,
        target_changeset_ids=target_changesets,
    )
    planned_action_by_key = {
        (action.epic_id, action.changeset_id): action for action in planned_actions
    }

    drift_records = prefix_migration_drift.scan_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        repo_slug=repo_slug,
        git_path=git_path,
        target_epic_id=selected_epic,
        target_changeset_ids=target_changesets,
    )
    diagnostics: list[str] = []
    for record in drift_records:
        drift_class = _normalize_drift_value(record.get("drift_class"))
        record_changeset_id = _normalize_drift_value(record.get("changeset_id"))
        if drift_class is None or record_changeset_id is None:
            continue
        if drift_class not in _BLOCKING_PREFIX_DRIFT_CLASSES:
            continue
        if record_changeset_id not in target_changesets:
            continue
        record_epic_id = _normalize_drift_value(record.get("epic_id")) or "<unknown>"
        action = planned_action_by_key.get((record_epic_id, record_changeset_id))
        if drift_class == "metadata-read-failure":
            actionable = True
        elif action is None:
            actionable = True
        else:
            actionable = action.changed and drift_class in action.drift_classes
        if not actionable:
            continue

        raw_values = record.get("values")
        details = dict(raw_values) if isinstance(raw_values, dict) else {}
        if action is not None:
            details["repair.changed"] = action.changed
            details["repair.canonical_work_branch"] = action.canonical_work_branch
            details["repair.canonical_worktree_path"] = action.canonical_worktree_path
            details["repair.update_mapping"] = action.update_mapping
            details["repair.update_changeset_metadata"] = action.update_changeset_metadata
            details["repair.update_changeset_worktree_path"] = action.update_changeset_worktree_path
        values_json = _format_drift_values(details)
        diagnostics.append(
            "check=prefix-migration-preflight "
            f"epic={record_epic_id} "
            f"changeset={record_changeset_id} "
            f"drift_class={drift_class} "
            f"values={values_json}"
        )
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, selected_epic))
    expected_root_branch = _normalize_branch(root_branch_value)
    expected_parent_branch = _normalize_branch(changeset_parent_branch)
    expected_work_branch: str | None
    if changeset_id == selected_epic:
        expected_work_branch = expected_root_branch
    else:
        mapped_work_branch = (
            _normalize_branch(mapping.changesets.get(changeset_id)) if mapping is not None else None
        )
        if expected_root_branch is None:
            expected_work_branch = mapped_work_branch
        else:
            expected_work_branch = mapped_work_branch or worktrees.derive_changeset_branch(
                expected_root_branch, changeset_id
            )
    if changeset_id == selected_epic:
        try:
            issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            raise RuntimeError(
                "startup preflight blocked: unable to read selected changeset metadata "
                f"(bd show exit {code})"
            ) from exc
        issue = issues[0] if issues else None
        if issue is not None:
            lineage_fields = (
                (
                    "changeset.root_branch",
                    _normalize_branch(changeset_fields.root_branch(issue)),
                    expected_root_branch,
                ),
                (
                    "changeset.parent_branch",
                    _normalize_branch(changeset_fields.parent_branch(issue)),
                    expected_parent_branch,
                ),
                (
                    "changeset.work_branch",
                    _normalize_branch(changeset_fields.work_branch(issue)),
                    expected_work_branch,
                ),
            )
            for field_name, current_value, expected_value in lineage_fields:
                if current_value is None or expected_value is None:
                    continue
                if current_value == expected_value:
                    continue
                if field_name == "changeset.parent_branch" and allow_parent_branch_override:
                    continue
                diagnostics.append(
                    "check=lineage-override-risk "
                    f"epic={selected_epic} "
                    f"changeset={changeset_id} "
                    "drift_class=field-mismatch "
                    "values="
                    + _format_drift_values(
                        {
                            "field": field_name,
                            "current": current_value,
                            "expected": expected_value,
                        }
                    )
                )
    if not diagnostics:
        return

    ordered_diagnostics = tuple(sorted(diagnostics))
    details = "\n".join(f"- {line}" for line in ordered_diagnostics)
    raise RuntimeError(
        "startup preflight blocked: read-only mode detected migration drift that requires "
        "explicit normalization.\n"
        f"epic={selected_epic} changeset={changeset_id}\n"
        "Remediation: run `atelier doctor --fix`, verify drift is "
        "cleared, then rerun startup.\n"
        "Deterministic diagnostics:\n"
        f"{details}"
    )


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def _mapping_ownership_from_beads(
    *, beads_root: Path, repo_root: Path
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    owner_by_changeset: dict[str, str] = {}
    epic_root_branches: dict[str, str] = {}
    epic_worktree_paths: dict[str, str] = {}
    epic_issues = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    for issue in epic_issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str):
            continue
        epic_id = issue_id.strip()
        if not epic_id:
            continue
        root_branch = beads.extract_workspace_root_branch(issue)
        if root_branch:
            epic_root_branches[epic_id] = root_branch
        worktree_path = beads.extract_worktree_path(issue)
        if worktree_path:
            epic_worktree_paths[epic_id] = worktree_path
        work_children = beads.list_work_children(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if not work_children:
            owner_by_changeset.setdefault(epic_id, epic_id)
        descendants = beads.list_descendant_changesets(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        for descendant in descendants:
            descendant_id = descendant.get("id")
            if not isinstance(descendant_id, str):
                continue
            normalized_descendant = descendant_id.strip()
            if not normalized_descendant:
                continue
            owner_by_changeset.setdefault(normalized_descendant, epic_id)
    return owner_by_changeset, epic_root_branches, epic_worktree_paths


def _normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _normalize_relpath(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return _normalize_branch(fields.get("workspace.parent_branch"))


def _sync_child_workspace_parent_branch(
    *,
    selected_epic: str,
    changeset_id: str,
    root_branch_value: str,
    epic_parent_branch: str,
    beads_root: Path,
    repo_root: Path,
    control: WorktreePreparationControl,
) -> None:
    if not changeset_id or changeset_id == selected_epic:
        return
    normalized_epic_parent = _normalize_branch(epic_parent_branch)
    if not normalized_epic_parent:
        return
    if root_branch_value and normalized_epic_parent == root_branch_value:
        return
    try:
        issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        control.say(
            "Skipped workspace.parent_branch alignment for "
            f"{changeset_id}: unable to read metadata from beads (bd show exit {code})"
        )
        return
    if not issues:
        return
    current_parent = _extract_workspace_parent_branch(issues[0])
    if current_parent == normalized_epic_parent:
        return
    if current_parent and current_parent != root_branch_value:
        control.say(
            "Skipped workspace.parent_branch alignment for "
            f"{changeset_id}: preserving existing non-root value {current_parent!r} "
            f"instead of epic parent {normalized_epic_parent!r}"
        )
        return
    beads.update_workspace_parent_branch(
        changeset_id,
        normalized_epic_parent,
        beads_root=beads_root,
        cwd=repo_root,
        allow_override=bool(current_parent and current_parent == root_branch_value),
    )
    control.say(f"Aligned workspace.parent_branch for {changeset_id}: {normalized_epic_parent}")


def _reconcile_epic_changeset_lineage(
    *,
    selected_epic: str,
    changeset_id: str,
    canonical_root_branch: str,
    beads_root: Path,
    repo_root: Path,
    control: WorktreePreparationControl,
) -> None:
    issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"unable to load changeset metadata for {changeset_id!r}"
        )
    issue = issues[0]
    workspace_root = _normalize_branch(beads.extract_workspace_root_branch(issue))
    metadata_root = _normalize_branch(changeset_fields.root_branch(issue))
    metadata_work = _normalize_branch(changeset_fields.work_branch(issue))
    canonical = _normalize_branch(canonical_root_branch)
    if canonical is None:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: missing canonical root branch metadata"
        )

    if (
        workspace_root is None
        and metadata_root is None
        and metadata_work is not None
        and metadata_work != canonical
    ):
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"workspace.root_branch and changeset.root_branch are unset, "
            f"but changeset.work_branch={metadata_work!r} conflicts with "
            f"canonical root {canonical!r}"
        )

    conflicting_metadata = {
        value
        for value in (metadata_root, metadata_work)
        if value is not None and value != canonical
    }
    if len(conflicting_metadata) > 1:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"workspace.root_branch={workspace_root!r}, "
            f"changeset.root_branch={metadata_root!r}, "
            f"changeset.work_branch={metadata_work!r}, "
            f"canonical={canonical!r}"
        )

    if workspace_root is None:
        beads.update_workspace_root_branch(
            selected_epic,
            canonical,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        control.say(f"Reconciled workspace.root_branch for {selected_epic}: {canonical}")

    if metadata_root != canonical or metadata_work != canonical:
        beads.update_changeset_branch_metadata(
            changeset_id,
            root_branch=canonical,
            parent_branch=None,
            work_branch=canonical,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        control.say(
            f"Reconciled epic-as-changeset lineage for {changeset_id}: "
            f"root={canonical}, work={canonical}"
        )


@dataclass(frozen=True)
class _LineageRepairDecision:
    root_branch: str
    parent_branch: str
    work_branch: str
    work_branch_source: str
    worktree_relpath: str
    worktree_source: str
    metadata_changed: bool
    mapping_changed: bool

    @property
    def changed(self) -> bool:
        return self.metadata_changed or self.mapping_changed


def _mapped_worktree_lineage(
    *,
    project_data_dir: Path,
    mapping: worktrees.WorktreeMapping,
    changeset_id: str,
    git_path: str | None,
) -> tuple[str | None, str | None]:
    mapped_relpath = _normalize_relpath(mapping.changeset_worktrees.get(changeset_id))
    if mapped_relpath is None:
        return None, None
    mapped_path_raw = Path(mapped_relpath)
    mapped_path = (
        mapped_path_raw if mapped_path_raw.is_absolute() else project_data_dir / mapped_path_raw
    )
    if not mapped_path.exists() or not (mapped_path / ".git").exists():
        return None, mapped_relpath
    branch = _normalize_branch(git.git_current_branch(mapped_path, git_path=git_path))
    if branch is None or branch == "HEAD":
        return None, mapped_relpath
    return branch, mapped_relpath


def _unique_branches(*values: str | None) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        if value is None:
            continue
        if value in ordered:
            continue
        ordered.append(value)
    return tuple(ordered)


def _lookup_open_pr_head(
    *,
    repo_slug: str | None,
    branch_candidates: tuple[str, ...],
) -> str | None:
    if repo_slug is None:
        return None
    for candidate in branch_candidates:
        lookup = prs.lookup_github_pr_status(repo_slug, candidate)
        if lookup.failed:
            continue
        payload = lookup.payload if lookup.found else None
        if not isinstance(payload, dict):
            continue
        state = str(payload.get("state") or "").strip().upper()
        if state != "OPEN":
            continue
        head_branch = _normalize_branch(payload.get("headRefName"))
        if head_branch is not None:
            return head_branch
    return None


def _resolve_lineage_repair(
    *,
    project_data_dir: Path,
    repo_slug: str | None,
    changeset_id: str,
    root_branch_value: str,
    parent_branch_value: str,
    mapping: worktrees.WorktreeMapping,
    issue: dict[str, object],
    git_path: str | None,
) -> _LineageRepairDecision:
    metadata_root = _normalize_branch(changeset_fields.root_branch(issue))
    metadata_parent = _normalize_branch(changeset_fields.parent_branch(issue))
    metadata_work = _normalize_branch(changeset_fields.work_branch(issue))
    mapping_work = _normalize_branch(mapping.changesets.get(changeset_id))
    mapping_relpath = _normalize_relpath(mapping.changeset_worktrees.get(changeset_id))
    mapped_branch, mapped_relpath = _mapped_worktree_lineage(
        project_data_dir=project_data_dir,
        mapping=mapping,
        changeset_id=changeset_id,
        git_path=git_path,
    )
    normalized_root = _normalize_branch(root_branch_value) or _normalize_branch(mapping.root_branch)
    if normalized_root is None:
        raise RuntimeError("changeset lineage repair blocked: missing canonical root branch")
    normalized_parent = _normalize_branch(parent_branch_value) or metadata_parent or normalized_root
    derived_work = worktrees.derive_changeset_branch(normalized_root, changeset_id)
    pr_head = _lookup_open_pr_head(
        repo_slug=repo_slug,
        branch_candidates=_unique_branches(
            metadata_work, mapping_work, derived_work, mapped_branch
        ),
    )

    if pr_head is not None:
        canonical_work = pr_head
        work_source = "open-pr-head"
    elif mapped_branch is not None:
        canonical_work = mapped_branch
        work_source = "checked-out-worktree"
    elif mapping_work is not None:
        canonical_work = mapping_work
        work_source = "mapping"
    elif metadata_work is not None:
        canonical_work = metadata_work
        work_source = "metadata"
    else:
        canonical_work = derived_work
        work_source = "derived"

    if mapped_relpath is not None:
        canonical_relpath = mapped_relpath
        relpath_source = "checked-out-worktree"
    elif mapping_relpath is not None:
        canonical_relpath = mapping_relpath
        relpath_source = "mapping"
    else:
        canonical_relpath = worktrees.changeset_worktree_relpath(changeset_id)
        relpath_source = "default"

    metadata_changed = (
        metadata_root != normalized_root
        or metadata_parent != normalized_parent
        or metadata_work != canonical_work
    )
    mapping_changed = mapping_work != canonical_work or mapping_relpath != canonical_relpath
    return _LineageRepairDecision(
        root_branch=normalized_root,
        parent_branch=normalized_parent,
        work_branch=canonical_work,
        work_branch_source=work_source,
        worktree_relpath=canonical_relpath,
        worktree_source=relpath_source,
        metadata_changed=metadata_changed,
        mapping_changed=mapping_changed,
    )


def _repair_non_epic_changeset_lineage(
    *,
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None,
    selected_epic: str,
    changeset_id: str,
    current_branch: str,
    root_branch_value: str,
    parent_branch_value: str,
    mapping: worktrees.WorktreeMapping,
    git_path: str | None,
    control: WorktreePreparationControl,
) -> tuple[str, worktrees.WorktreeMapping]:
    try:
        issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        control.say(
            "Skipped non-epic lineage repair for "
            f"{changeset_id}: unable to load metadata (bd show exit {code})"
        )
        return current_branch, mapping
    if not issues:
        control.say(
            f"Skipped non-epic lineage repair for {changeset_id}: metadata not found in beads"
        )
        return current_branch, mapping
    try:
        decision = _resolve_lineage_repair(
            project_data_dir=project_data_dir,
            repo_slug=repo_slug,
            changeset_id=changeset_id,
            root_branch_value=root_branch_value,
            parent_branch_value=parent_branch_value,
            mapping=mapping,
            issue=issues[0],
            git_path=git_path,
        )
    except RuntimeError as exc:
        control.say(f"Skipped non-epic lineage repair for {changeset_id}: {exc}")
        return current_branch, mapping
    if not decision.changed:
        return decision.work_branch, mapping

    if decision.metadata_changed:
        beads.update_changeset_branch_metadata(
            changeset_id,
            root_branch=decision.root_branch,
            parent_branch=decision.parent_branch,
            work_branch=decision.work_branch,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
    updated_mapping = mapping
    if decision.mapping_changed:
        updated_mapping, _changed = worktrees.reconcile_changeset_lineage_entries(
            project_data_dir,
            selected_epic,
            changeset_id,
            work_branch=decision.work_branch,
            worktree_relpath=decision.worktree_relpath,
        )
    control.say(
        f"Repaired changeset lineage for {changeset_id}: "
        f"root={decision.root_branch}, parent={decision.parent_branch}, "
        f"work={decision.work_branch} ({decision.work_branch_source}), "
        f"worktree={decision.worktree_relpath} ({decision.worktree_source})"
    )
    return decision.work_branch, updated_mapping


def prepare_worktrees(
    *,
    context: WorktreePreparationContext,
    control: WorktreePreparationControl,
) -> WorktreePreparation:
    """Ensure epic/changeset worktrees and branch metadata exist."""
    dry_run = context.dry_run
    project_data_dir = context.project_data_dir
    repo_root = context.repo_root
    beads_root = context.beads_root
    selected_epic = context.selected_epic
    changeset_id = context.changeset_id
    root_branch_value = context.root_branch_value
    changeset_parent_branch = context.changeset_parent_branch
    allow_parent_branch_override = context.allow_parent_branch_override
    git_path = context.git_path
    epic_parent_branch = context.epic_parent_branch
    epic_worktree_path: Path | None = None
    changeset_worktree_path: Path | None = None
    branch: str | None = None
    epic_is_changeset = bool(changeset_id) and changeset_id == selected_epic

    if dry_run:
        mapping = None
        mapping_path = worktrees.mapping_path(project_data_dir, selected_epic)
        if mapping_path.exists():
            mapping = worktrees.load_mapping(mapping_path)
        epic_worktree_path = (
            project_data_dir / mapping.worktree_path
            if mapping and mapping.worktree_path
            else worktrees.worktree_dir(project_data_dir, selected_epic)
        )
        if epic_is_changeset and root_branch_value:
            branch = root_branch_value
        elif mapping and changeset_id in mapping.changesets:
            branch = mapping.changesets[changeset_id]
        elif root_branch_value:
            branch = worktrees.derive_changeset_branch(root_branch_value, changeset_id)
        if epic_is_changeset:
            changeset_worktree_path = epic_worktree_path
        else:
            changeset_relpath = None
            if mapping and changeset_id in mapping.changeset_worktrees:
                changeset_relpath = mapping.changeset_worktrees[changeset_id]
            elif changeset_id:
                changeset_relpath = worktrees.changeset_worktree_relpath(changeset_id)
            if changeset_relpath:
                changeset_worktree_path = project_data_dir / changeset_relpath
        control.dry_run_log(f"Epic worktree: {epic_worktree_path}")
        if changeset_worktree_path is not None:
            control.dry_run_log(f"Changeset worktree: {changeset_worktree_path}")
        else:
            control.dry_run_log("Changeset worktree: <unknown>")
        control.dry_run_log(f"Changeset branch: {branch or '<unknown>'}")
        if changeset_id:
            control.dry_run_log(
                "Would update changeset branch metadata "
                f"(root={root_branch_value!r}, "
                f"parent={changeset_parent_branch!r}, "
                f"work={branch!r}, "
                f"allow_override={allow_parent_branch_override!r})."
            )
        control.dry_run_log("Would ensure git worktrees and checkout.")
        return WorktreePreparation(
            epic_worktree_path=epic_worktree_path,
            changeset_worktree_path=changeset_worktree_path,
            branch=branch,
        )

    _startup_worktree_preflight(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        selected_epic=selected_epic,
        changeset_id=changeset_id,
        root_branch_value=root_branch_value,
        changeset_parent_branch=changeset_parent_branch,
        allow_parent_branch_override=allow_parent_branch_override,
        git_path=git_path,
    )

    owner_by_changeset, epic_root_branches, epic_worktree_paths = _mapping_ownership_from_beads(
        beads_root=beads_root,
        repo_root=repo_root,
    )
    synthesis_diagnostics: dict[str, worktrees.MappingSynthesisDiagnostic] = {}
    changed_mappings = worktrees.reconcile_mapping_ownership(
        project_data_dir,
        owner_by_changeset=owner_by_changeset,
        epic_root_branches=epic_root_branches,
        epic_worktree_paths=epic_worktree_paths,
        synthesis_diagnostics=synthesis_diagnostics,
    )
    if changed_mappings:
        control.say("Reconciled mapping ownership: " + ", ".join(changed_mappings))
    for epic_id in sorted(synthesis_diagnostics):
        diagnostic = synthesis_diagnostics[epic_id]
        if diagnostic.worktree_path_source == "metadata":
            path_note = "preserved from issue metadata"
        elif diagnostic.worktree_path_source == "lineage":
            path_note = "preserved from source mapping lineage"
        else:
            path_note = "synthesized default"
        control.say(
            f"Mapping path synthesis for {epic_id}: {path_note} ({diagnostic.worktree_path})"
        )

    repo_slug = prs.github_repo_slug(git.git_origin_url(repo_root))
    epic_worktree_path = worktrees.ensure_git_worktree(
        project_data_dir,
        repo_root,
        selected_epic,
        root_branch=root_branch_value,
        git_path=git_path,
    )
    branch, mapping = worktrees.ensure_changeset_branch(
        project_data_dir,
        selected_epic,
        changeset_id,
        root_branch=root_branch_value,
        repo_root=repo_root,
        git_path=git_path,
    )
    beads.update_worktree_path(
        selected_epic,
        mapping.worktree_path,
        beads_root=beads_root,
        cwd=repo_root,
        allow_override=True,
    )
    if epic_is_changeset:
        _reconcile_epic_changeset_lineage(
            selected_epic=selected_epic,
            changeset_id=changeset_id,
            canonical_root_branch=root_branch_value,
            beads_root=beads_root,
            repo_root=repo_root,
            control=control,
        )
    else:
        branch, mapping = _repair_non_epic_changeset_lineage(
            project_data_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            repo_slug=repo_slug,
            selected_epic=selected_epic,
            changeset_id=changeset_id,
            current_branch=branch,
            root_branch_value=root_branch_value,
            parent_branch_value=changeset_parent_branch,
            mapping=mapping,
            git_path=git_path,
            control=control,
        )
    if epic_is_changeset:
        changeset_worktree_path = epic_worktree_path
    else:
        changeset_worktree_path = worktrees.ensure_changeset_worktree(
            project_data_dir,
            repo_root,
            selected_epic,
            changeset_id,
            branch=branch,
            root_branch=root_branch_value,
            parent_branch=changeset_parent_branch,
            git_path=git_path,
        )
    worktrees.ensure_changeset_checkout(
        changeset_worktree_path,
        branch,
        root_branch=root_branch_value,
        parent_branch=changeset_parent_branch,
        git_path=git_path,
    )
    _sync_child_workspace_parent_branch(
        selected_epic=selected_epic,
        changeset_id=changeset_id,
        root_branch_value=root_branch_value,
        epic_parent_branch=epic_parent_branch,
        beads_root=beads_root,
        repo_root=repo_root,
        control=control,
    )
    if changeset_id:
        root_base = git.git_rev_parse(changeset_worktree_path, root_branch_value, git_path=git_path)
        parent_base = git.git_rev_parse(
            changeset_worktree_path,
            changeset_parent_branch,
            git_path=git_path,
        )
        beads.update_changeset_branch_metadata(
            changeset_id,
            root_branch=root_branch_value,
            parent_branch=changeset_parent_branch,
            work_branch=branch,
            root_base=None if allow_parent_branch_override else root_base,
            parent_base=parent_base,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=allow_parent_branch_override,
        )
    control.say(f"Epic worktree: {epic_worktree_path}")
    control.say(f"Changeset worktree: {changeset_worktree_path}")
    control.say(f"Changeset branch: {branch}")
    return WorktreePreparation(
        epic_worktree_path=epic_worktree_path,
        changeset_worktree_path=changeset_worktree_path,
        branch=branch,
    )
