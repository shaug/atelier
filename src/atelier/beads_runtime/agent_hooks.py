"""Agent hook and epic claim flows extracted from ``atelier.beads``."""

from __future__ import annotations

import json

from .. import lifecycle
from ..worker.models_boundary import parse_issue_boundary
from . import issue_mutations
from .client import FailureHandler, RuntimeBeadsClient


def release_epic_assignment(
    epic_id: str,
    *,
    expected_assignee: str | None,
    expected_hooked: bool | None,
    client: RuntimeBeadsClient,
    hooked_label: str = "at:hooked",
) -> bool:
    """Release epic ownership with optional assignee/hook preconditions."""
    with client.issue_write_lock(epic_id):
        issues = client.run(["show", epic_id], json_mode=True)
        if not issues:
            return False
        issue = issues[0]
        labels = _issue_labels(issue)
        status = str(issue.get("status") or "")
        assignee_raw = issue.get("assignee")
        assignee = (
            assignee_raw.strip() if isinstance(assignee_raw, str) and assignee_raw.strip() else None
        )
        expected_assignee_normalized = issue_mutations.normalize_description_field_value(
            expected_assignee
        )
        if expected_assignee is not None and assignee != expected_assignee_normalized:
            return False
        if (
            expected_hooked is not None
            and _has_issue_label(labels, hooked_label) != expected_hooked
        ):
            return False

        args = ["update", epic_id, "--assignee", ""]
        if _has_issue_label(labels, hooked_label):
            args.extend(["--remove-label", hooked_label])
        if status and status not in {"closed", "done"}:
            args.extend(["--status", "open"])
        client.run(args, allow_failure=True)
        refreshed = client.run(["show", epic_id], json_mode=True)
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
        if _has_issue_label(_issue_labels(updated), hooked_label):
            return False
        return True


def _slot_show_hook(
    agent_bead_id: str,
    *,
    client: RuntimeBeadsClient,
) -> str | None:
    result = client.run(
        ["slot", "show", agent_bead_id, "--json"],
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
    return _extract_hook_from_slot_payload(payload)


def _slot_set_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    client: RuntimeBeadsClient,
    hook_slot_name: str,
) -> None:
    client.run(
        ["slot", "set", agent_bead_id, hook_slot_name, epic_id],
        allow_failure=True,
    )


def get_agent_hook(
    agent_bead_id: str,
    *,
    client: RuntimeBeadsClient,
    hook_slot_name: str,
) -> str | None:
    """Return the currently hooked epic id for an agent bead."""
    slot_hook = _slot_show_hook(
        agent_bead_id,
        client=client,
    )
    if slot_hook:
        return slot_hook
    issues = client.run(["show", agent_bead_id], json_mode=True)
    if not issues:
        return None
    issue = issues[0]
    fields = issue_mutations.parse_description_fields(_issue_description(issue))
    hook = _normalize_hook_value(fields.get("hook_bead"))
    if hook:
        _slot_set_hook(
            agent_bead_id,
            hook,
            client=client,
            hook_slot_name=hook_slot_name,
        )
    return hook


def clear_agent_hook(
    agent_bead_id: str,
    *,
    expected_hook: str | None,
    client: RuntimeBeadsClient,
    fail: FailureHandler,
    hook_slot_name: str,
) -> None:
    """Clear the hooked epic id from slot and description state."""
    with client.issue_write_lock(agent_bead_id):
        issues = client.run(["show", agent_bead_id], json_mode=True)
        if not issues:
            fail(f"agent bead not found: {agent_bead_id}")
        current_hook = get_agent_hook(
            agent_bead_id,
            client=client,
            hook_slot_name=hook_slot_name,
        )
        if expected_hook is not None and current_hook != _normalize_hook_value(expected_hook):
            return
        if current_hook is None:
            return
        client.run(
            ["slot", "clear", agent_bead_id, hook_slot_name],
            allow_failure=True,
        )
        issue_mutations.update_issue_description_fields(
            agent_bead_id,
            fields={"hook_bead": None},
            expected_current={"hook_bead": current_hook},
            require_expected_match=True,
            client=client,
            fail=fail,
        )


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    allow_takeover_from: str | None,
    client: RuntimeBeadsClient,
    fail: FailureHandler,
    hooked_label: str = "at:hooked",
    epic_label: str = "at:epic",
) -> dict[str, object]:
    """Claim an epic by assigning it to the current agent."""

    def claim_is_complete(candidate: dict[str, object], *, claimant: str) -> bool:
        assignee = candidate.get("assignee")
        status = str(candidate.get("status") or "").strip().lower()
        return (
            isinstance(assignee, str)
            and assignee == claimant
            and status == "in_progress"
            and _has_issue_label(_issue_labels(candidate), hooked_label)
        )

    with client.issue_write_lock(epic_id):
        issues = client.run(["show", epic_id], json_mode=True)
        if not issues:
            fail(f"epic not found: {epic_id}")
        issue = issues[0]
        labels = _issue_labels(issue)
        issue_type = lifecycle.issue_payload_type(issue)
        parent_id = _issue_parent_id(issue)
        claimability = _evaluate_epic_claimability(issue)
        is_executable_work = lifecycle.is_executable_epic_identity(
            labels=labels,
            issue_type=issue_type,
            parent_id=parent_id,
        )

        if is_executable_work and not bool(getattr(claimability, "claimable", False)):
            reasons = getattr(claimability, "reasons", ())
            detail = ", ".join(reasons)
            fail(
                f"epic {epic_id} is not claimable under lifecycle contract ({detail}); "
                "require top-level work in open/in_progress status"
            )
        if is_executable_work and _is_planner_assignee(agent_id):
            fail(
                f"epic {epic_id} claim rejected for planner {agent_id}; "
                "planner agents cannot claim executable work"
            )

        raw_existing_assignee = issue.get("assignee")
        existing_assignee = (
            raw_existing_assignee.strip()
            if isinstance(raw_existing_assignee, str) and raw_existing_assignee.strip()
            else None
        )
        if _is_planner_assignee(existing_assignee) and is_executable_work:
            fail(
                f"epic {epic_id} is assigned to planner {existing_assignee}; "
                "planner agents cannot own executable work"
            )
        if (
            existing_assignee
            and existing_assignee != agent_id
            and existing_assignee != allow_takeover_from
        ):
            fail(f"epic {epic_id} already has an assignee")

        if (
            existing_assignee
            and allow_takeover_from
            and existing_assignee == allow_takeover_from
            and existing_assignee != agent_id
        ):
            released = release_epic_assignment(
                epic_id,
                expected_assignee=allow_takeover_from,
                expected_hooked=_has_issue_label(labels, hooked_label),
                client=client,
                hooked_label=hooked_label,
            )
            if not released:
                fail(f"epic {epic_id} takeover failed; claim ownership changed")

        claim_result = client.run(
            ["update", epic_id, "--claim"],
            allow_failure=True,
        )
        if getattr(claim_result, "returncode", 1) != 0:
            refreshed = client.run(["show", epic_id], json_mode=True)
            assignee = None
            if refreshed:
                candidate_assignee = refreshed[0].get("assignee")
                if isinstance(candidate_assignee, str) and candidate_assignee.strip():
                    assignee = candidate_assignee.strip()
            if assignee != agent_id:
                fail(f"epic {epic_id} already has an assignee")

        update_args = [
            "update",
            epic_id,
            "--status",
            "in_progress",
            "--add-label",
            hooked_label,
        ]
        if _is_standalone_changeset_without_epic_label(
            issue,
            client=client,
            epic_label=epic_label,
        ):
            update_args.extend(["--add-label", epic_label])

        for attempt in range(2):
            client.run(
                update_args,
                allow_failure=True,
            )
            refreshed = client.run(["show", epic_id], json_mode=True)
            if not refreshed:
                continue
            updated = refreshed[0]
            assignee = updated.get("assignee")
            if assignee != agent_id:
                fail(f"epic {epic_id} claim failed; already assigned")
            if claim_is_complete(updated, claimant=agent_id):
                return updated
            if attempt == 0:
                continue
            fail(
                f"epic {epic_id} claim failed; expected status=in_progress and label {hooked_label}"
            )

        fail(f"epic {epic_id} claim failed; unable to verify claimed state")
        return issue


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    client: RuntimeBeadsClient,
    fail: FailureHandler,
    hook_slot_name: str,
) -> None:
    """Persist hook state for an agent bead in slot + description fields."""
    with client.issue_write_lock(agent_bead_id):
        issues = client.run(["show", agent_bead_id], json_mode=True)
        if not issues:
            fail(f"agent bead not found: {agent_bead_id}")
        client.run(
            ["slot", "set", agent_bead_id, hook_slot_name, epic_id],
            allow_failure=True,
        )
        issue_mutations.update_issue_description_fields(
            agent_bead_id,
            fields={"hook_bead": epic_id},
            client=client,
            fail=fail,
        )


def _issue_labels(issue: dict[str, object]) -> set[str]:
    return lifecycle.normalized_labels(issue.get("labels"))


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    try:
        boundary = parse_issue_boundary(issue, source="beads_runtime:issue_parent_id")
    except ValueError:
        return None
    return boundary.parent_id


def _evaluate_epic_claimability(issue: dict[str, object]) -> lifecycle.EpicClaimEvaluation:
    return lifecycle.evaluate_epic_claimability(
        status=issue.get("status"),
        labels=_issue_labels(issue),
        issue_type=lifecycle.issue_payload_type(issue),
        parent_id=_issue_parent_id(issue),
    )


def _is_standalone_changeset_without_epic_label(
    issue: dict[str, object],
    *,
    client: RuntimeBeadsClient,
    epic_label: str,
) -> bool:
    labels = _issue_labels(issue)
    if _has_issue_label(labels, epic_label):
        return False
    if not lifecycle.is_work_issue(
        labels=labels,
        issue_type=lifecycle.issue_payload_type(issue),
    ):
        return False
    try:
        boundary = parse_issue_boundary(issue, source="beads_runtime:claim_epic")
    except ValueError:
        return False
    if boundary.parent_id is not None:
        return False
    issue_id = issue.get("id")
    if not isinstance(issue_id, str) or not issue_id.strip():
        return False
    work_children = client.run(
        ["list", "--parent", issue_id.strip()],
        json_mode=True,
    )
    return not any(
        lifecycle.is_work_issue(
            labels=_issue_labels(child),
            issue_type=lifecycle.issue_payload_type(child),
        )
        for child in work_children
        if isinstance(child, dict)
    )


def _has_issue_label(labels: set[str] | list[str], label: str) -> bool:
    label_values = {
        candidate.strip().lower()
        for candidate in labels
        if isinstance(candidate, str) and candidate.strip()
    }
    cleaned_label = label.strip().lower()
    if not cleaned_label:
        return False
    if cleaned_label in label_values:
        return True
    label_name = _label_name(cleaned_label)
    if not label_name:
        return False
    suffix = f":{label_name}"
    return any(candidate.endswith(suffix) for candidate in label_values)


def _label_name(label: str) -> str:
    cleaned = label.strip().lower()
    if not cleaned:
        return ""
    return cleaned.rsplit(":", 1)[-1]


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    return description if isinstance(description, str) else ""


def _normalize_hook_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "null":
            return None
        return cleaned
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _extract_hook_from_slot_payload(payload: object) -> str | None:
    if isinstance(payload, str):
        return _normalize_hook_value(payload)
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
    if "slots" in payload and isinstance(payload["slots"], dict):
        return _extract_hook_from_slot_payload(payload["slots"].get("hook"))
    if "id" in payload:
        return _normalize_hook_value(payload.get("id"))
    if "issue_id" in payload:
        return _normalize_hook_value(payload.get("issue_id"))
    if "bead_id" in payload:
        return _normalize_hook_value(payload.get("bead_id"))
    if "bead" in payload:
        return _normalize_hook_value(payload.get("bead"))
    return None


def _agent_role(agent_id: object) -> str | None:
    if not isinstance(agent_id, str):
        return None
    parts = [part for part in agent_id.split("/") if part]
    if len(parts) >= 2 and parts[0] == "atelier":
        return parts[1].strip().lower() or None
    if parts:
        value = parts[0].strip().lower()
        return value or None
    return None


def _is_planner_assignee(agent_id: object) -> bool:
    return _agent_role(agent_id) == "planner"
