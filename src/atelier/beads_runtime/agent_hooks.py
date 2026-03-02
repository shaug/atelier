"""Agent hook and epic claim flows extracted from ``atelier.beads``."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

RunBdJson = Callable[..., list[dict[str, object]]]
RunBdCommand = Callable[..., object]
IssueWriteLock = Callable[[str, Path], AbstractContextManager[None]]


def release_epic_assignment(
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    expected_assignee: str | None,
    expected_hooked: bool | None,
    issue_write_lock: IssueWriteLock,
    run_bd_json: RunBdJson,
    run_bd_command: RunBdCommand,
    issue_labels: Callable[[dict[str, object]], set[str]],
    has_issue_label: Callable[[set[str] | list[str], str], bool],
    issue_label: Callable[[str], str],
    label_hooked: str = "hooked",
    normalize_description_field_value: Callable[[str | None], str | None],
) -> bool:
    """Release epic ownership with optional assignee/hook preconditions."""
    with issue_write_lock(epic_id, beads_root):
        issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            return False
        issue = issues[0]
        labels = issue_labels(issue)
        status = str(issue.get("status") or "")
        assignee_raw = issue.get("assignee")
        assignee = (
            assignee_raw.strip() if isinstance(assignee_raw, str) and assignee_raw.strip() else None
        )
        expected_assignee_normalized = normalize_description_field_value(expected_assignee)
        if expected_assignee is not None and assignee != expected_assignee_normalized:
            return False
        if expected_hooked is not None:
            has_hooked = has_issue_label(labels, label_hooked)
            if has_hooked != expected_hooked:
                return False

        args = ["update", epic_id, "--assignee", ""]
        if has_issue_label(labels, label_hooked):
            args.extend(["--remove-label", issue_label(label_hooked)])
        if status and status not in {"closed", "done"}:
            args.extend(["--status", "open"])
        run_bd_command(args, beads_root=beads_root, cwd=cwd, allow_failure=True)
        refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
        if not refreshed:
            return False
        updated = refreshed[0]
        updated_assignee_raw = updated.get("assignee")
        updated_assignee = (
            updated_assignee_raw.strip()
            if isinstance(updated_assignee_raw, str) and updated_assignee_raw.strip()
            else None
        )
        if updated_assignee is not None:
            return False
        if has_issue_label(issue_labels(updated), label_hooked):
            return False
        return True


def _slot_show_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_command: RunBdCommand,
    extract_hook_from_slot_payload: Callable[[object], str | None],
) -> str | None:
    result = run_bd_command(
        ["slot", "show", agent_bead_id, "--json"],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    if getattr(result, "returncode", 1) != 0:
        return None
    raw_output = getattr(result, "stdout", "") or ""
    raw = raw_output.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return extract_hook_from_slot_payload(payload)


def _slot_set_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_command: RunBdCommand,
    hook_slot_name: str,
) -> None:
    run_bd_command(
        ["slot", "set", agent_bead_id, hook_slot_name, epic_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )


def get_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_command: RunBdCommand,
    run_bd_json: RunBdJson,
    parse_description_fields: Callable[[str | None], dict[str, str]],
    normalize_hook_value: Callable[[object], str | None],
    extract_hook_from_slot_payload: Callable[[object], str | None],
    hook_slot_name: str,
) -> str | None:
    """Return the currently hooked epic id for an agent bead."""
    slot_hook = _slot_show_hook(
        agent_bead_id,
        beads_root=beads_root,
        cwd=cwd,
        run_bd_command=run_bd_command,
        extract_hook_from_slot_payload=extract_hook_from_slot_payload,
    )
    if slot_hook:
        return slot_hook
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return None
    issue = issues[0]
    description = issue.get("description")
    fields = parse_description_fields(description if isinstance(description, str) else "")
    hook = normalize_hook_value(fields.get("hook_bead"))
    if hook:
        _slot_set_hook(
            agent_bead_id,
            hook,
            beads_root=beads_root,
            cwd=cwd,
            run_bd_command=run_bd_command,
            hook_slot_name=hook_slot_name,
        )
    return hook


def clear_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    expected_hook: str | None,
    issue_write_lock: IssueWriteLock,
    run_bd_json: RunBdJson,
    run_bd_command: RunBdCommand,
    get_agent_hook_impl: Callable[..., str | None],
    normalize_hook_value: Callable[[object], str | None],
    update_description_fields_optimistic: Callable[..., dict[str, object]],
    hook_slot_name: str,
    die: Callable[[str], None],
) -> None:
    """Clear the hooked epic id from slot and description state."""
    with issue_write_lock(agent_bead_id, beads_root):
        issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            die(f"agent bead not found: {agent_bead_id}")
        current_hook = get_agent_hook_impl(agent_bead_id, beads_root=beads_root, cwd=cwd)
        if expected_hook is not None and current_hook != normalize_hook_value(expected_hook):
            return
        if current_hook is None:
            return
        run_bd_command(
            ["slot", "clear", agent_bead_id, hook_slot_name],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        update_description_fields_optimistic(
            agent_bead_id,
            fields={"hook_bead": None},
            expected_current={"hook_bead": current_hook},
            require_expected_match=True,
            beads_root=beads_root,
            cwd=cwd,
        )


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_takeover_from: str | None,
    issue_write_lock: IssueWriteLock,
    run_bd_json: RunBdJson,
    run_bd_command: RunBdCommand,
    issue_labels: Callable[[dict[str, object]], set[str]],
    evaluate_epic_claimability: Callable[[dict[str, object]], object],
    lifecycle_is_executable_epic_identity: Callable[..., bool],
    lifecycle_issue_payload_type: Callable[[dict[str, object]], object],
    issue_parent_id: Callable[[dict[str, object]], str | None],
    is_planner_assignee: Callable[[object], bool],
    release_epic_assignment_impl: Callable[..., bool],
    is_standalone_changeset_without_epic_label: Callable[..., bool],
    has_issue_label: Callable[[set[str] | list[str], str], bool],
    issue_label: Callable[[str], str],
    label_hooked: str = "hooked",
    label_epic: str = "epic",
    die: Callable[[str], None],
) -> dict[str, object]:
    """Claim an epic by assigning it to the current agent."""

    def claim_is_complete(candidate: dict[str, object], *, claimant: str) -> bool:
        assignee = candidate.get("assignee")
        status = str(candidate.get("status") or "").strip().lower()
        return (
            isinstance(assignee, str)
            and assignee == claimant
            and status == "in_progress"
            and has_issue_label(issue_labels(candidate), label_hooked)
        )

    with issue_write_lock(epic_id, beads_root):
        issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            die(f"epic not found: {epic_id}")
        issue = issues[0]
        claimability = evaluate_epic_claimability(issue)
        is_executable_work = lifecycle_is_executable_epic_identity(
            labels=issue_labels(issue),
            issue_type=lifecycle_issue_payload_type(issue),
            parent_id=issue_parent_id(issue),
        )
        if is_executable_work and not bool(getattr(claimability, "claimable", False)):
            reasons = getattr(claimability, "reasons", ())
            detail = ", ".join(reasons)
            die(
                f"epic {epic_id} is not claimable under lifecycle contract ({detail}); "
                "require top-level work in open/in_progress status"
            )
        if is_executable_work and is_planner_assignee(agent_id):
            die(
                f"epic {epic_id} claim rejected for planner {agent_id}; "
                "planner agents cannot claim executable work"
            )
        raw_existing_assignee = issue.get("assignee")
        existing_assignee = (
            raw_existing_assignee.strip()
            if isinstance(raw_existing_assignee, str) and raw_existing_assignee.strip()
            else None
        )
        if is_planner_assignee(existing_assignee) and is_executable_work:
            die(
                f"epic {epic_id} is assigned to planner {existing_assignee}; "
                "planner agents cannot own executable work"
            )
        if (
            existing_assignee
            and existing_assignee != agent_id
            and existing_assignee != allow_takeover_from
        ):
            die(f"epic {epic_id} already has an assignee")

        if (
            existing_assignee
            and allow_takeover_from
            and existing_assignee == allow_takeover_from
            and existing_assignee != agent_id
        ):
            released = release_epic_assignment_impl(
                epic_id,
                beads_root=beads_root,
                cwd=cwd,
                expected_assignee=allow_takeover_from,
                expected_hooked=has_issue_label(issue_labels(issue), label_hooked),
            )
            if not released:
                die(f"epic {epic_id} takeover failed; claim ownership changed")

        claim_result = run_bd_command(
            ["update", epic_id, "--claim"],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if getattr(claim_result, "returncode", 1) != 0:
            refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
            assignee = None
            if refreshed:
                candidate_assignee = refreshed[0].get("assignee")
                if isinstance(candidate_assignee, str) and candidate_assignee.strip():
                    assignee = candidate_assignee.strip()
            if assignee != agent_id:
                die(f"epic {epic_id} already has an assignee")

        update_args = [
            "update",
            epic_id,
            "--status",
            "in_progress",
            "--add-label",
            issue_label(label_hooked),
        ]
        if is_standalone_changeset_without_epic_label(issue, beads_root=beads_root, cwd=cwd):
            update_args.extend(["--add-label", issue_label(label_epic)])
        for attempt in range(2):
            run_bd_command(
                update_args,
                beads_root=beads_root,
                cwd=cwd,
                allow_failure=True,
            )
            refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
            if not refreshed:
                continue
            updated = refreshed[0]
            assignee = updated.get("assignee")
            if assignee != agent_id:
                die(f"epic {epic_id} claim failed; already assigned")
            if claim_is_complete(updated, claimant=agent_id):
                return updated
            if attempt == 0:
                continue
            die(
                f"epic {epic_id} claim failed; expected status=in_progress and label "
                f"{issue_label(label_hooked)}"
            )
        die(f"epic {epic_id} claim failed; unable to verify claimed state")
        return issue


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    issue_write_lock: IssueWriteLock,
    run_bd_json: RunBdJson,
    run_bd_command: RunBdCommand,
    update_description_fields_optimistic: Callable[..., dict[str, object]],
    hook_slot_name: str,
    die: Callable[[str], None],
) -> None:
    """Persist hook state for an agent bead in slot + description fields."""
    with issue_write_lock(agent_bead_id, beads_root):
        issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            die(f"agent bead not found: {agent_bead_id}")
        run_bd_command(
            ["slot", "set", agent_bead_id, hook_slot_name, epic_id],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        update_description_fields_optimistic(
            agent_bead_id,
            fields={"hook_bead": epic_id},
            beads_root=beads_root,
            cwd=cwd,
        )
