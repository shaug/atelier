"""Garbage collection for stale Atelier state."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .. import agent_home, beads, changesets, config, git, lifecycle, messages, worktrees
from .. import exec as exec_util
from .. import log as atelier_log
from ..io import confirm, die, say, select, warn
from . import work as work_cmd
from .resolve import resolve_current_project_with_repo_root


@dataclass(frozen=True)
class GcAction:
    description: str
    apply: Callable[[], None]
    details: tuple[str, ...] = ()


def _log_debug(message: str) -> None:
    atelier_log.debug(f"[gc] {message}")


def _log_warning(message: str) -> None:
    atelier_log.warning(f"[gc] {message}")


def _run_git_gc_command(args: list[str], *, repo_root: Path, git_path: str) -> tuple[bool, str]:
    _log_debug(f"git command start args={' '.join(args)}")
    result = exec_util.try_run_command(
        git.git_command(["-C", str(repo_root), *args], git_path=git_path)
    )
    if result is None:
        _log_warning(f"git command missing executable args={' '.join(args)}")
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _log_warning(f"git command failed args={' '.join(args)} detail={detail or 'none'}")
        return False, detail or f"command failed: git {' '.join(args)}"
    _log_debug(f"git command ok args={' '.join(args)}")
    return True, (result.stdout or "").strip()


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
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def _issue_sort_key(issue: dict[str, object]) -> str:
    issue_id = issue.get("id")
    if isinstance(issue_id, str):
        return issue_id
    return ""


def _changeset_review_state(issue: dict[str, object]) -> str:
    description = issue.get("description")
    review = changesets.parse_review_metadata(description if isinstance(description, str) else "")
    return (review.pr_state or "").strip().lower()


def _resolve_changeset_status_for_migration(
    issue: dict[str, object],
) -> tuple[str | None, tuple[str, ...]]:
    if not lifecycle.is_work_issue(
        labels=_issue_labels(issue),
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
    labels = _issue_labels(issue)
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


def _workspace_branch_from_labels(labels: set[str]) -> str | None:
    for label in labels:
        if not label.startswith("workspace:"):
            continue
        candidate = label.split(":", 1)[1].strip()
        if candidate:
            return candidate
    return None


def _try_show_issue(issue_id: str, *, beads_root: Path, cwd: Path) -> dict[str, object] | None:
    try:
        records = beads.run_bd_issue_records(
            ["show", issue_id], beads_root=beads_root, cwd=cwd, source="_try_show_issue"
        )
    except ValueError:
        return None
    if records:
        return records[0].raw
    return None


def _issue_integrated_sha(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    integrated = fields.get("changeset.integrated_sha")
    if isinstance(integrated, str):
        value = integrated.strip()
        if value and value.lower() != "null":
            return value
    notes = issue.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return None
    for line in notes.splitlines():
        if "changeset.integrated_sha" not in line:
            continue
        _prefix, _sep, suffix = line.partition(":")
        value = suffix.strip()
        if value and value.lower() != "null":
            return value
    return None


def _is_merged_closed_changeset(issue: dict[str, object]) -> bool:
    if lifecycle.canonical_lifecycle_status(issue.get("status")) != "closed":
        return False
    if _issue_integrated_sha(issue):
        return True
    return _changeset_review_state(issue) == "merged"


def _reconcile_preview_lines(
    epic_id: str,
    changesets: list[str],
    *,
    project_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
) -> tuple[str, ...]:
    lines: list[str] = []
    if project_dir is not None:
        mapping = worktrees.load_mapping(worktrees.mapping_path(project_dir, epic_id))
        if mapping is not None:
            branch_values = [mapping.root_branch, *mapping.changesets.values()]
            branches = sorted({value for value in branch_values if value})
            worktree_values = [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            worktree_paths = sorted({value for value in worktree_values if value})
            lines.append(
                f"mapped branches ({len(branches)}): "
                + (", ".join(branches) if branches else "(none)")
            )
            lines.append(
                f"mapped worktrees ({len(worktree_paths)}): "
                + (", ".join(worktree_paths) if worktree_paths else "(none)")
            )
    epic_issue = _try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
    if epic_issue:
        description_raw = epic_issue.get("description")
        description = description_raw if isinstance(description_raw, str) else None
        fields = beads.parse_description_fields(description)
        root_branch = _normalize_branch(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = _normalize_branch(fields.get("changeset.root_branch"))
        parent_branch = _normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = _normalize_branch(fields.get("changeset.parent_branch"))
        if root_branch or parent_branch:
            lines.append(
                f"final integration: {root_branch or 'unset'} -> {parent_branch or 'unset'}"
            )
    if changesets:
        lines.append(f"changesets to reconcile: {', '.join(changesets)}")
    for changeset_id in changesets:
        issue = _try_show_issue(changeset_id, beads_root=beads_root, cwd=repo_root)
        if not issue:
            lines.append(f"{changeset_id}: status=unknown integrated_sha=missing")
            continue
        status = str(issue.get("status") or "unknown")
        integrated_sha = _issue_integrated_sha(issue) or "missing"
        lines.append(f"{changeset_id}: status={status} integrated_sha={integrated_sha}")
    return tuple(lines)


def _gc_normalize_changeset_labels(
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
    for issue in sorted(issues, key=_issue_sort_key):
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


def _gc_remove_at_changeset_label(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    """Remove deprecated at:changeset label; changeset role is inferred from graph."""
    actions: list[GcAction] = []
    issues = beads.run_bd_json(
        ["list", "--label", "at:changeset", "--all"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in sorted(issues, key=_issue_sort_key):
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        issue_id = issue_id.strip()

        def _apply_remove(
            bead_id: str = issue_id,
        ) -> None:
            beads.run_bd_command(
                ["update", bead_id, "--remove-label", "at:changeset"],
                beads_root=beads_root,
                cwd=repo_root,
            )

        actions.append(
            GcAction(
                description=f"Remove deprecated at:changeset label from {issue_id}",
                apply=_apply_remove,
                details=("changeset role inferred from graph",),
            )
        )
    return actions


def _gc_normalize_executable_ready_labels(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    actions: list[GcAction] = []
    issues = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    for issue in sorted(issues, key=_issue_sort_key):
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

        def _apply_normalize(bead_id: str = issue_id, status_value: str = status_value) -> None:
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


def _release_epic(epic: dict[str, object], *, beads_root: Path, cwd: Path) -> None:
    epic_id = str(epic.get("id") or "")
    if not epic_id:
        return
    labels = _issue_labels(epic)
    status = str(epic.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=cwd, allow_failure=True)


def _gc_hooks(
    *,
    beads_root: Path,
    repo_root: Path,
    stale_hours: float,
    include_missing_heartbeat: bool,
) -> list[GcAction]:
    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_delta = dt.timedelta(hours=stale_hours)
    actions: list[GcAction] = []

    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )
    agents: dict[str, dict[str, object]] = {}
    for issue in agent_issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = fields.get("agent_id") or issue.get("title")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        agent_id = agent_id.strip()
        if not agent_id:
            continue
        issue_id = issue.get("id") if isinstance(issue, dict) else None
        hook_bead = None
        if isinstance(issue_id, str) and issue_id:
            hook_bead = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        if not hook_bead:
            hook_bead = fields.get("hook_bead")
        agents[agent_id] = {
            "issue": issue,
            "issue_id": issue_id,
            "fields": fields,
            "hook_bead": hook_bead,
            "heartbeat_at": fields.get("heartbeat_at"),
        }

    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)

    for agent_id, payload in agents.items():
        hook_bead = payload.get("hook_bead")
        if not isinstance(hook_bead, str) or not hook_bead:
            continue
        heartbeat_raw = payload.get("heartbeat_at")
        heartbeat = _parse_rfc3339(heartbeat_raw if isinstance(heartbeat_raw, str) else None)
        stale = False
        if heartbeat is None:
            stale = include_missing_heartbeat
        else:
            stale = now - heartbeat > stale_delta
        if not stale:
            continue
        issue = payload.get("issue")
        issue_id = issue.get("id") if isinstance(issue, dict) else None
        if not isinstance(issue_id, str) or not issue_id:
            continue
        epic = _try_show_issue(hook_bead, beads_root=beads_root, cwd=repo_root)
        description = f"Release stale hook for {agent_id} (epic {hook_bead})"

        def _apply_release(
            agent_bead_id: str = issue_id,
            epic_issue: dict[str, object] | None = epic,
        ) -> None:
            if epic_issue:
                _release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
            beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)

        actions.append(GcAction(description=description, apply=_apply_release))

    for epic in epics:
        labels = _issue_labels(epic)
        assignee = epic.get("assignee")
        epic_id = epic.get("id")
        description = epic.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        claim_expires_raw = fields.get("claim_expires_at")
        claim_expires_at = _parse_rfc3339(
            claim_expires_raw if isinstance(claim_expires_raw, str) else None
        )
        if "at:hooked" not in labels and not assignee and claim_expires_at is None:
            continue
        if not isinstance(epic_id, str) or not epic_id:
            continue
        status = str(epic.get("status") or "").lower()
        assignee_id = assignee if isinstance(assignee, str) else ""
        agent_info = agents.get(assignee_id) if assignee_id else None
        hook_bead = agent_info.get("hook_bead") if agent_info else None
        if claim_expires_at is not None and claim_expires_at <= now:
            description = f"Release expired claim for epic {epic_id}"

            def _apply_expired(
                epic_issue: dict[str, object] = epic,
                agent_payload: dict[str, object] | None = agent_info,
                epic_id_value: str = epic_id,
            ) -> None:
                _release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
                if agent_payload and agent_payload.get("hook_bead") == epic_id_value:
                    agent_issue_id = agent_payload.get("issue_id")
                    if isinstance(agent_issue_id, str) and agent_issue_id:
                        beads.clear_agent_hook(agent_issue_id, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_expired))
            continue

        if claim_expires_at is not None and "at:hooked" not in labels and not assignee:
            continue

        if status in {"closed", "done"} and ("at:hooked" in labels or assignee):
            description = f"Release closed epic hook {epic_id}"

            def _apply_closed(
                epic_issue: dict[str, object] = epic,
                agent_payload: dict[str, object] | None = agent_info,
                epic_id_value: str = epic_id,
            ) -> None:
                _release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
                if agent_payload and agent_payload.get("hook_bead") == epic_id_value:
                    agent_issue_id = agent_payload.get("issue_id")
                    if isinstance(agent_issue_id, str) and agent_issue_id:
                        beads.clear_agent_hook(agent_issue_id, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_closed))
            continue

        if not agent_info or hook_bead != epic_id:
            description = f"Release orphaned epic hook {epic_id}"

            def _apply_unhook(epic_issue: dict[str, object] = epic) -> None:
                _release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_unhook))
    return actions


def _normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _branch_lookup_ref(
    repo_root: Path, branch: str, *, git_path: str
) -> tuple[str | None, str | None]:
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/origin/{branch}"
    local = branch if git.git_ref_exists(repo_root, local_ref, git_path=git_path) else None
    remote = (
        f"origin/{branch}" if git.git_ref_exists(repo_root, remote_ref, git_path=git_path) else None
    )
    return local, remote


def _branch_integrated_into_target(
    repo_root: Path,
    *,
    branch: str,
    target_ref: str,
    git_path: str,
) -> bool:
    local_ref, remote_ref = _branch_lookup_ref(repo_root, branch, git_path=git_path)
    branch_refs = [ref for ref in (local_ref, remote_ref) if ref]
    if not branch_refs:
        return True
    for branch_ref in branch_refs:
        is_ancestor = git.git_is_ancestor(repo_root, branch_ref, target_ref, git_path=git_path)
        if is_ancestor is True:
            return True
        fully_applied = git.git_branch_fully_applied(
            repo_root, target_ref, branch_ref, git_path=git_path
        )
        if fully_applied is True:
            return True
    return False


def _gc_resolved_epic_artifacts(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
    assume_yes: bool = False,
) -> list[GcAction]:
    actions: list[GcAction] = []
    meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
    if not meta_dir.exists():
        return actions
    default_branch = git.git_default_branch(repo_root, git_path=git_path) or ""
    for path in meta_dir.glob("*.json"):
        mapping = worktrees.load_mapping(path)
        if not mapping:
            continue
        epic_id = mapping.epic_id
        if not epic_id:
            continue
        epic = _try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
        if not epic:
            continue
        status = str(epic.get("status") or "").strip().lower()
        if status not in {"closed", "done"}:
            continue

        description = epic.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        parent_branch = _normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = _normalize_branch(fields.get("changeset.parent_branch"))
        if not parent_branch:
            parent_branch = _normalize_branch(default_branch)
        if not parent_branch:
            continue

        target_local, target_remote = _branch_lookup_ref(
            repo_root, parent_branch, git_path=git_path
        )
        target_ref = target_local or target_remote
        if not target_ref:
            continue

        branches = {mapping.root_branch, *mapping.changesets.values()}
        prunable_branches = {
            branch
            for branch in branches
            if branch and branch != parent_branch and branch != default_branch
        }
        if any(
            not _branch_integrated_into_target(
                repo_root, branch=branch, target_ref=target_ref, git_path=git_path
            )
            for branch in prunable_branches
        ):
            continue

        relpaths = {
            relpath
            for relpath in [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            if relpath
        }
        existing_worktrees = []
        for relpath in relpaths:
            worktree_path = Path(relpath)
            if not worktree_path.is_absolute():
                worktree_path = project_dir / worktree_path
            if worktree_path.exists() and (worktree_path / ".git").exists():
                existing_worktrees.append(worktree_path)

        has_prunable_branch_ref = False
        for branch in prunable_branches:
            local_ref, remote_ref = _branch_lookup_ref(repo_root, branch, git_path=git_path)
            if local_ref or remote_ref:
                has_prunable_branch_ref = True
                break
        if not existing_worktrees and not has_prunable_branch_ref:
            continue

        description_text = f"Prune resolved epic artifacts for {epic_id}"
        changeset_worktree_summary = ", ".join(sorted(mapping.changeset_worktrees.values()))
        if not changeset_worktree_summary:
            changeset_worktree_summary = "(none)"
        branch_summary = ", ".join(sorted(prunable_branches))
        if not branch_summary:
            branch_summary = "(none)"
        details = (
            f"epic worktree: {mapping.worktree_path}",
            f"changeset worktrees: {changeset_worktree_summary}",
            f"branches to prune: {branch_summary}",
            f"integration target: {target_ref}",
        )

        def _apply_cleanup(
            epic_value: str = epic_id,
            mapping_path: Path = path,
            worktree_paths: list[Path] = list(existing_worktrees),
            branches_to_prune: list[str] = sorted(prunable_branches),
        ) -> None:
            _log_debug(
                f"cleanup resolved epic start epic={epic_value} "
                f"worktrees={len(worktree_paths)} branches={len(branches_to_prune)}"
            )
            for worktree_path in worktree_paths:
                status_lines = git.git_status_porcelain(worktree_path, git_path=git_path)
                force_remove = False
                if status_lines:
                    say(f"Resolved worktree has local changes: {worktree_path}")
                    for line in status_lines[:20]:
                        say(f"- {line}")
                    if len(status_lines) > 20:
                        say(f"- ... ({len(status_lines) - 20} more)")
                    if assume_yes:
                        force_remove = True
                    else:
                        choice = select(
                            "Resolved worktree cleanup action",
                            ("force-remove", "exit"),
                            "exit",
                        )
                        if choice != "force-remove":
                            die("gc aborted by user")
                        force_remove = True
                _log_debug(f"removing resolved worktree path={worktree_path} force={force_remove}")
                args = ["worktree", "remove"]
                if force_remove:
                    args.append("--force")
                args.append(str(worktree_path))
                ok, detail = _run_git_gc_command(args, repo_root=repo_root, git_path=git_path)
                if not ok:
                    die(detail)

            current_branch = git.git_current_branch(repo_root, git_path=git_path)
            for branch in branches_to_prune:
                local_ref, remote_ref = _branch_lookup_ref(repo_root, branch, git_path=git_path)
                if remote_ref:
                    _log_debug(f"deleting remote branch branch={branch} epic={epic_value}")
                    _run_git_gc_command(
                        ["push", "origin", "--delete", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )
                if local_ref and current_branch != branch:
                    _log_debug(f"deleting local branch branch={branch} epic={epic_value}")
                    _run_git_gc_command(
                        ["branch", "-D", branch], repo_root=repo_root, git_path=git_path
                    )
            # Remove stale mapping once worktrees/branches are pruned.
            mapping_path.unlink(missing_ok=True)
            _log_debug(f"cleanup resolved epic complete epic={epic_value}")

        actions.append(
            GcAction(
                description=description_text,
                apply=_apply_cleanup,
                details=details,
            )
        )
    return actions


def _gc_closed_workspace_branches_without_mapping(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
) -> list[GcAction]:
    actions: list[GcAction] = []
    default_branch = git.git_default_branch(repo_root, git_path=git_path) or ""
    issues = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        status = str(issue.get("status") or "").strip().lower()
        if status not in {"closed", "done"}:
            continue
        labels = _issue_labels(issue)
        if not _is_merged_closed_changeset(issue):
            continue
        workspace_branch = _workspace_branch_from_labels(labels)
        if not workspace_branch:
            continue
        mapping_path = worktrees.mapping_path(project_dir, issue_id.strip())
        if mapping_path.exists():
            continue

        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        root_branch = _normalize_branch(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = _normalize_branch(fields.get("changeset.root_branch"))
        if not root_branch:
            root_branch = _normalize_branch(workspace_branch)
        parent_branch = _normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = _normalize_branch(fields.get("changeset.parent_branch"))
        if not parent_branch or parent_branch == root_branch:
            parent_branch = _normalize_branch(default_branch) or parent_branch
        if not root_branch or not parent_branch:
            continue

        target_local, target_remote = _branch_lookup_ref(
            repo_root, parent_branch, git_path=git_path
        )
        target_ref = target_local or target_remote
        if not target_ref:
            continue

        work_branch = _normalize_branch(fields.get("changeset.work_branch"))
        candidate_values = [root_branch, work_branch, workspace_branch]
        candidate_branches = {value for value in candidate_values if value}
        prunable_branches = {
            branch
            for branch in candidate_branches
            if branch and branch != parent_branch and branch != default_branch
        }
        if not prunable_branches:
            continue
        if any(
            not _branch_integrated_into_target(
                repo_root, branch=branch, target_ref=target_ref, git_path=git_path
            )
            for branch in prunable_branches
        ):
            continue

        has_prunable_branch_ref = False
        for branch in prunable_branches:
            local_ref, remote_ref = _branch_lookup_ref(repo_root, branch, git_path=git_path)
            if local_ref or remote_ref:
                has_prunable_branch_ref = True
                break
        if not has_prunable_branch_ref:
            continue

        description_text = f"Prune closed workspace branches for {issue_id.strip()}"
        details = (
            f"workspace branch: {workspace_branch}",
            f"root branch: {root_branch}",
            f"work branch: {work_branch or '(none)'}",
            f"integration target: {target_ref}",
            f"branches to prune: {', '.join(sorted(prunable_branches))}",
        )

        def _apply_cleanup(
            branches_to_prune: list[str] = sorted(prunable_branches),
        ) -> None:
            current_branch = git.git_current_branch(repo_root, git_path=git_path)
            for branch in branches_to_prune:
                local_ref, remote_ref = _branch_lookup_ref(repo_root, branch, git_path=git_path)
                if remote_ref:
                    _log_debug(f"deleting remote workspace branch branch={branch}")
                    _run_git_gc_command(
                        ["push", "origin", "--delete", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )
                if local_ref and current_branch != branch:
                    _log_debug(f"deleting local workspace branch branch={branch}")
                    _run_git_gc_command(
                        ["branch", "-D", branch], repo_root=repo_root, git_path=git_path
                    )

        actions.append(
            GcAction(
                description=description_text,
                apply=_apply_cleanup,
                details=details,
            )
        )
    return actions


def _gc_orphan_worktrees(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
    assume_yes: bool = False,
) -> list[GcAction]:
    actions: list[GcAction] = []
    meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
    if not meta_dir.exists():
        return actions
    for path in meta_dir.glob("*.json"):
        mapping = worktrees.load_mapping(path)
        if not mapping:
            continue
        epic_id = mapping.epic_id
        if not epic_id:
            continue
        epic = _try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
        if epic is not None:
            continue
        description = f"Remove orphaned worktree for epic {epic_id}"

        def _apply_remove(
            epic: str = epic_id,
            mapping_path: Path = path,
            mapping_worktree_path: str = mapping.worktree_path,
        ) -> None:
            worktree_path = Path(mapping_worktree_path)
            if not worktree_path.is_absolute():
                worktree_path = project_dir / worktree_path
            status_lines = git.git_status_porcelain(worktree_path, git_path=git_path)
            force_remove = False
            if status_lines:
                say(f"Orphaned worktree has local changes: {worktree_path}")
                for line in status_lines[:20]:
                    say(f"- {line}")
                if len(status_lines) > 20:
                    say(f"- ... ({len(status_lines) - 20} more)")
                if assume_yes:
                    force_remove = True
                else:
                    choice = select(
                        "Orphaned worktree cleanup action",
                        ("force-remove", "exit"),
                        "exit",
                    )
                    if choice != "force-remove":
                        die("gc aborted by user")
                    force_remove = True
            _log_debug(
                f"removing orphaned worktree epic={epic} path={worktree_path} force={force_remove}"
            )
            worktrees.remove_git_worktree(
                project_dir,
                repo_root,
                epic,
                git_path=git_path,
                force=force_remove,
            )
            mapping_path.unlink(missing_ok=True)
            _log_debug(f"removed orphaned worktree epic={epic}")

        actions.append(
            GcAction(
                description=description,
                apply=_apply_remove,
                details=(
                    f"mapping: {path}",
                    f"worktree: {mapping.worktree_path}",
                ),
            )
        )
    return actions


def _gc_message_claims(
    *,
    beads_root: Path,
    repo_root: Path,
    stale_hours: float,
) -> list[GcAction]:
    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_delta = dt.timedelta(hours=stale_hours)
    actions: list[GcAction] = []
    issues = beads.run_bd_json(
        ["list", "--label", "at:message"], beads_root=beads_root, cwd=repo_root
    )
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        queue = payload.metadata.get("queue")
        claimed_at = payload.metadata.get("claimed_at")
        if not queue or not isinstance(claimed_at, str):
            continue
        claimed_time = _parse_rfc3339(claimed_at)
        if claimed_time is None or now - claimed_time <= stale_delta:
            continue
        description_text = f"Release stale queue claim for message {issue_id}"

        def _apply_release(
            message_id: str = issue_id,
            body: str = payload.body,
            metadata: dict[str, object] = dict(payload.metadata),
        ) -> None:
            metadata["claimed_by"] = None
            metadata["claimed_at"] = None
            updated = messages.render_message(metadata, body)
            with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(updated)
                temp_path = handle.name
            try:
                beads.run_bd_command(
                    ["update", message_id, "--body-file", temp_path],
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            finally:
                Path(temp_path).unlink(missing_ok=True)

        actions.append(GcAction(description=description_text, apply=_apply_release))
    return actions


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _gc_message_retention(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    now = dt.datetime.now(tz=dt.timezone.utc)
    actions: list[GcAction] = []
    issues = beads.run_bd_json(
        ["list", "--label", "at:message"], beads_root=beads_root, cwd=repo_root
    )
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        channel = payload.metadata.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            continue
        expires_at = payload.metadata.get("expires_at")
        retention_days = _coerce_float(payload.metadata.get("retention_days"))
        expiry_time: dt.datetime | None = None
        if isinstance(expires_at, str):
            expiry_time = _parse_rfc3339(expires_at)
        if expiry_time is None and retention_days is not None:
            created_at_raw = issue.get("created_at")
            created_at = _parse_rfc3339(created_at_raw if isinstance(created_at_raw, str) else None)
            if created_at is not None:
                expiry_time = created_at + dt.timedelta(days=retention_days)
        if expiry_time is None or now < expiry_time:
            continue
        description_text = f"Close expired channel message {issue_id}"

        def _apply_close(message_id: str = issue_id) -> None:
            beads.run_bd_command(
                ["close", message_id],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )

        actions.append(GcAction(description=description_text, apply=_apply_close))
    return actions


def _gc_agent_homes(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    actions: list[GcAction] = []
    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )
    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    epics_by_id: dict[str, dict[str, object]] = {}
    epics_by_assignee: dict[str, list[dict[str, object]]] = {}
    for epic in epics:
        epic_id = epic.get("id")
        if isinstance(epic_id, str) and epic_id:
            epics_by_id[epic_id] = epic
        assignee = epic.get("assignee")
        if not isinstance(assignee, str):
            continue
        assignee_id = assignee.strip()
        if not assignee_id:
            continue
        epics_by_assignee.setdefault(assignee_id, []).append(epic)

    for issue in agent_issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = fields.get("agent_id") or issue.get("title") or ""
        if not isinstance(agent_id, str) or not agent_id.strip():
            continue
        agent_id = agent_id.strip()
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        if agent_home.session_pid_from_agent_id(agent_id) is None:
            continue
        if agent_home.is_session_agent_active(agent_id):
            continue
        hook_bead = None
        if issue_id:
            hook_bead = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        if not hook_bead:
            hook_bead = fields.get("hook_bead")

        dependent_epics: list[dict[str, object]] = []
        dependent_epic_ids: set[str] = set()
        if isinstance(hook_bead, str) and hook_bead:
            hooked_epic = epics_by_id.get(hook_bead)
            if hooked_epic is not None:
                dependent_epics.append(hooked_epic)
                dependent_epic_ids.add(hook_bead)
        for epic in epics_by_assignee.get(agent_id, []):
            epic_id = epic.get("id")
            if not isinstance(epic_id, str) or not epic_id:
                continue
            if epic_id in dependent_epic_ids:
                continue
            dependent_epics.append(epic)
            dependent_epic_ids.add(epic_id)

        description_text = f"Prune stale session agent bead for {agent_id}"

        def _apply_remove(
            agent: str = agent_id,
            agent_bead_id: str = issue_id,
            has_hook: bool = isinstance(hook_bead, str) and bool(hook_bead),
            epics_to_release: tuple[dict[str, object], ...] = tuple(dependent_epics),
        ) -> None:
            for epic_issue in epics_to_release:
                _release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
            if has_hook:
                beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
            beads.run_bd_command(
                ["close", agent_bead_id],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
            agent_home.cleanup_agent_home_by_id(project_dir, agent)

        actions.append(GcAction(description=description_text, apply=_apply_remove))
    return actions


def gc(args: object) -> None:
    """Garbage collect stale hooks and orphaned worktrees."""
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    stale_hours = getattr(args, "stale_hours", 24.0)
    try:
        stale_hours = float(stale_hours)
    except (TypeError, ValueError):
        warn("invalid --stale-hours value; defaulting to 24")
        stale_hours = 24.0
    if stale_hours < 0:
        stale_hours = 0

    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    reconcile = bool(getattr(args, "reconcile", False))
    include_missing_heartbeat = bool(getattr(args, "stale_if_missing_heartbeat", False))
    _log_debug(
        "gc start "
        f"dry_run={dry_run} yes={yes} reconcile={reconcile} "
        f"stale_hours={stale_hours} include_missing_heartbeat={include_missing_heartbeat}"
    )

    if reconcile:
        git_path = config.resolve_git_path(project_config)
        candidates = work_cmd.list_reconcile_epic_candidates(
            project_config=project_config,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=git_path,
        )
        if not candidates:
            say("No reconcile candidates.")
            _log_debug("reconcile candidates none")
        if dry_run or yes:
            if not candidates:
                say("Reconcile blocked changesets: scanned=0, actionable=0, reconciled=0, failed=0")
                return
            for epic_id, changesets in candidates.items():
                _log_debug(
                    f"reconcile candidate epic={epic_id} changesets={len(changesets)} mode={'dry-run' if dry_run else 'yes'}"
                )
                say(f"Reconcile candidate: epic {epic_id} ({len(changesets)} merged changesets)")
                for detail in _reconcile_preview_lines(
                    epic_id,
                    changesets,
                    project_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                ):
                    say(f"- {detail}")
            reconcile_result = work_cmd.reconcile_blocked_merged_changesets(
                agent_id="atelier/system/gc",
                agent_bead_id="",
                project_config=project_config,
                project_data_dir=project_data_dir,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                dry_run=dry_run,
                log=say,
            )
            say(
                "Reconcile blocked changesets: "
                f"scanned={reconcile_result.scanned}, "
                f"actionable={reconcile_result.actionable}, "
                f"reconciled={reconcile_result.reconciled}, "
                f"failed={reconcile_result.failed}"
            )
            _log_debug(
                "reconcile totals "
                f"scanned={reconcile_result.scanned} actionable={reconcile_result.actionable} "
                f"reconciled={reconcile_result.reconciled} failed={reconcile_result.failed}"
            )
        else:
            total_scanned = 0
            total_actionable = 0
            total_reconciled = 0
            total_failed = 0
            for epic_id, changesets in candidates.items():
                preview = ", ".join(changesets[:3])
                if len(changesets) > 3:
                    preview = f"{preview}, +{len(changesets) - 3} more"
                prompt_text = (
                    f"Reconcile epic {epic_id} ({len(changesets)} merged changesets: {preview})?"
                )
                say(f"Reconcile candidate: epic {epic_id}")
                for detail in _reconcile_preview_lines(
                    epic_id,
                    changesets,
                    project_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                ):
                    say(f"- {detail}")
                if not confirm(prompt_text, default=False):
                    say(f"Skipped reconcile: epic {epic_id}")
                    _log_debug(f"reconcile skipped epic={epic_id}")
                    continue
                reconcile_result = work_cmd.reconcile_blocked_merged_changesets(
                    agent_id="atelier/system/gc",
                    agent_bead_id="",
                    project_config=project_config,
                    project_data_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    git_path=git_path,
                    epic_filter=epic_id,
                    changeset_filter=set(changesets),
                    dry_run=False,
                    log=say,
                )
                total_scanned += reconcile_result.scanned
                total_actionable += reconcile_result.actionable
                total_reconciled += reconcile_result.reconciled
                total_failed += reconcile_result.failed
                say(
                    f"Reconcile epic {epic_id}: "
                    f"scanned={reconcile_result.scanned}, "
                    f"actionable={reconcile_result.actionable}, "
                    f"reconciled={reconcile_result.reconciled}, "
                    f"failed={reconcile_result.failed}"
                )
                _log_debug(
                    f"reconcile epic={epic_id} scanned={reconcile_result.scanned} "
                    f"actionable={reconcile_result.actionable} reconciled={reconcile_result.reconciled} "
                    f"failed={reconcile_result.failed}"
                )
            say(
                "Reconcile blocked changesets: "
                f"scanned={total_scanned}, "
                f"actionable={total_actionable}, "
                f"reconciled={total_reconciled}, "
                f"failed={total_failed}"
            )
            _log_debug(
                "reconcile totals "
                f"scanned={total_scanned} actionable={total_actionable} "
                f"reconciled={total_reconciled} failed={total_failed}"
            )

    actions: list[GcAction] = []
    actions.extend(
        _gc_normalize_changeset_labels(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        _gc_remove_at_changeset_label(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        _gc_normalize_executable_ready_labels(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        _gc_hooks(
            beads_root=beads_root,
            repo_root=repo_root,
            stale_hours=stale_hours,
            include_missing_heartbeat=include_missing_heartbeat,
        )
    )
    actions.extend(
        _gc_orphan_worktrees(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
            assume_yes=yes,
        )
    )
    actions.extend(
        _gc_resolved_epic_artifacts(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
            assume_yes=yes,
        )
    )
    actions.extend(
        _gc_closed_workspace_branches_without_mapping(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
        )
    )
    actions.extend(
        _gc_message_claims(beads_root=beads_root, repo_root=repo_root, stale_hours=stale_hours)
    )
    actions.extend(_gc_message_retention(beads_root=beads_root, repo_root=repo_root))
    actions.extend(
        _gc_agent_homes(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )

    if not actions:
        say("No GC actions needed.")
        _log_debug("gc no actions")
        return

    for action in actions:
        _log_debug(f"gc action queued description={action.description}")
        say(f"GC action: {action.description}")
        for detail in action.details:
            say(f"- {detail}")
        if dry_run:
            say(f"Would: {action.description}")
            _log_debug(f"gc action dry-run description={action.description}")
            continue
        if yes or confirm(f"{action.description}?", default=False):
            say(f"Running: {action.description}")
            _log_debug(f"gc action run description={action.description}")
            action.apply()
            say(f"Done: {action.description}")
            _log_debug(f"gc action done description={action.description}")
        else:
            say(f"Skipped: {action.description}")
            _log_debug(f"gc action skipped description={action.description}")
