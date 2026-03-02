"""Agent hook and epic claim flows extracted from ``atelier.beads``."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

RunBdJson = Callable[..., list[dict[str, object]]]
RunBdCommand = Callable[..., object]
IssueWriteLock = Callable[[str, Path], AbstractContextManager[None]]


class AgentHooksRuntime(Protocol):
    """Typed runtime collaborator for claim/hook operations."""

    def issue_write_lock(self, issue_id: str, beads_root: Path) -> AbstractContextManager[None]:
        """Acquire an issue-scoped write lock context."""
        ...

    def run_bd_json(
        self, args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        """Execute a JSON ``bd`` command and parse payload."""
        ...

    def run_bd_command(
        self, args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        """Execute a raw ``bd`` command."""
        ...

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        """Return normalized issue labels."""
        ...

    def has_issue_label(self, labels: set[str] | list[str], name: str) -> bool:
        """Return whether a normalized label name exists."""
        ...

    def issue_label(self, name: str) -> str:
        """Render a prefixed label name."""
        ...

    def normalize_description_field_value(self, value: str | None) -> str | None:
        """Normalize description-backed string values."""
        ...

    def parse_description_fields(self, description: str | None) -> dict[str, str]:
        """Parse description frontmatter-like fields."""
        ...

    def normalize_hook_value(self, value: object) -> str | None:
        """Normalize hook identifier payload values."""
        ...

    def extract_hook_from_slot_payload(self, payload: object) -> str | None:
        """Extract hook id from ``bd slot show`` payloads."""
        ...

    def update_description_fields_optimistic(
        self,
        issue_id: str,
        *,
        fields: dict[str, str | None],
        expected_current: dict[str, str | None] | None = None,
        require_expected_match: bool = False,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object]:
        """Optimistically update description key/value fields."""
        ...

    def evaluate_epic_claimability(self, issue: dict[str, object]) -> object:
        """Evaluate lifecycle claimability for a candidate epic payload."""
        ...

    def lifecycle_is_executable_epic_identity(
        self,
        *,
        labels: set[str],
        issue_type: object,
        parent_id: str | None,
    ) -> bool:
        """Return whether payload should follow executable-work lifecycle rules."""
        ...

    def lifecycle_issue_payload_type(self, issue: dict[str, object]) -> object:
        """Return normalized lifecycle issue type."""
        ...

    def issue_parent_id(self, issue: dict[str, object]) -> str | None:
        """Return parent id for issue payload."""
        ...

    def is_planner_assignee(self, value: object) -> bool:
        """Return whether assignee identity is planner-scoped."""
        ...

    def release_epic_assignment(
        self,
        epic_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        expected_assignee: str | None = None,
        expected_hooked: bool | None = None,
    ) -> bool:
        """Release an existing epic assignment under preconditions."""
        ...

    def is_standalone_changeset_without_epic_label(
        self, issue: dict[str, object], *, beads_root: Path, cwd: Path
    ) -> bool:
        """Return whether a standalone changeset should backfill the epic label."""
        ...

    def get_agent_hook(self, agent_bead_id: str, *, beads_root: Path, cwd: Path) -> str | None:
        """Resolve current hook id for an agent bead."""
        ...

    def die(self, message: str) -> None:
        """Abort execution with a deterministic failure message."""
        ...


def release_epic_assignment(
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    expected_assignee: str | None,
    expected_hooked: bool | None,
    runtime: AgentHooksRuntime,
    label_hooked: str = "hooked",
) -> bool:
    """Release epic ownership with optional assignee/hook preconditions."""
    with runtime.issue_write_lock(epic_id, beads_root):
        issues = runtime.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            return False
        issue = issues[0]
        labels = runtime.issue_labels(issue)
        status = str(issue.get("status") or "")
        assignee_raw = issue.get("assignee")
        assignee = (
            assignee_raw.strip() if isinstance(assignee_raw, str) and assignee_raw.strip() else None
        )
        expected_assignee_normalized = runtime.normalize_description_field_value(expected_assignee)
        if expected_assignee is not None and assignee != expected_assignee_normalized:
            return False
        if expected_hooked is not None:
            has_hooked = runtime.has_issue_label(labels, label_hooked)
            if has_hooked != expected_hooked:
                return False

        args = ["update", epic_id, "--assignee", ""]
        if runtime.has_issue_label(labels, label_hooked):
            args.extend(["--remove-label", runtime.issue_label(label_hooked)])
        if status and status not in {"closed", "done"}:
            args.extend(["--status", "open"])
        runtime.run_bd_command(args, beads_root=beads_root, cwd=cwd, allow_failure=True)
        refreshed = runtime.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
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
        if runtime.has_issue_label(runtime.issue_labels(updated), label_hooked):
            return False
        return True


def _slot_show_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    runtime: AgentHooksRuntime,
) -> str | None:
    result = runtime.run_bd_command(
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
    return runtime.extract_hook_from_slot_payload(payload)


def _slot_set_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    runtime: AgentHooksRuntime,
    hook_slot_name: str,
) -> None:
    runtime.run_bd_command(
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
    runtime: AgentHooksRuntime,
    hook_slot_name: str,
) -> str | None:
    """Return the currently hooked epic id for an agent bead."""
    slot_hook = _slot_show_hook(
        agent_bead_id,
        beads_root=beads_root,
        cwd=cwd,
        runtime=runtime,
    )
    if slot_hook:
        return slot_hook
    issues = runtime.run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return None
    issue = issues[0]
    description = issue.get("description")
    fields = runtime.parse_description_fields(description if isinstance(description, str) else "")
    hook = runtime.normalize_hook_value(fields.get("hook_bead"))
    if hook:
        _slot_set_hook(
            agent_bead_id,
            hook,
            beads_root=beads_root,
            cwd=cwd,
            runtime=runtime,
            hook_slot_name=hook_slot_name,
        )
    return hook


def clear_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    expected_hook: str | None,
    runtime: AgentHooksRuntime,
    hook_slot_name: str,
) -> None:
    """Clear the hooked epic id from slot and description state."""
    with runtime.issue_write_lock(agent_bead_id, beads_root):
        issues = runtime.run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            runtime.die(f"agent bead not found: {agent_bead_id}")
        current_hook = runtime.get_agent_hook(agent_bead_id, beads_root=beads_root, cwd=cwd)
        if expected_hook is not None and current_hook != runtime.normalize_hook_value(
            expected_hook
        ):
            return
        if current_hook is None:
            return
        runtime.run_bd_command(
            ["slot", "clear", agent_bead_id, hook_slot_name],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        runtime.update_description_fields_optimistic(
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
    runtime: AgentHooksRuntime,
    label_hooked: str = "hooked",
    label_epic: str = "epic",
) -> dict[str, object]:
    """Claim an epic by assigning it to the current agent."""

    def claim_is_complete(candidate: dict[str, object], *, claimant: str) -> bool:
        assignee = candidate.get("assignee")
        status = str(candidate.get("status") or "").strip().lower()
        return (
            isinstance(assignee, str)
            and assignee == claimant
            and status == "in_progress"
            and runtime.has_issue_label(runtime.issue_labels(candidate), label_hooked)
        )

    with runtime.issue_write_lock(epic_id, beads_root):
        issues = runtime.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            runtime.die(f"epic not found: {epic_id}")
        issue = issues[0]
        claimability = runtime.evaluate_epic_claimability(issue)
        is_executable_work = runtime.lifecycle_is_executable_epic_identity(
            labels=runtime.issue_labels(issue),
            issue_type=runtime.lifecycle_issue_payload_type(issue),
            parent_id=runtime.issue_parent_id(issue),
        )
        if is_executable_work and not bool(getattr(claimability, "claimable", False)):
            reasons = getattr(claimability, "reasons", ())
            detail = ", ".join(reasons)
            runtime.die(
                f"epic {epic_id} is not claimable under lifecycle contract ({detail}); "
                "require top-level work in open/in_progress status"
            )
        if is_executable_work and runtime.is_planner_assignee(agent_id):
            runtime.die(
                f"epic {epic_id} claim rejected for planner {agent_id}; "
                "planner agents cannot claim executable work"
            )
        raw_existing_assignee = issue.get("assignee")
        existing_assignee = (
            raw_existing_assignee.strip()
            if isinstance(raw_existing_assignee, str) and raw_existing_assignee.strip()
            else None
        )
        if runtime.is_planner_assignee(existing_assignee) and is_executable_work:
            runtime.die(
                f"epic {epic_id} is assigned to planner {existing_assignee}; "
                "planner agents cannot own executable work"
            )
        if (
            existing_assignee
            and existing_assignee != agent_id
            and existing_assignee != allow_takeover_from
        ):
            runtime.die(f"epic {epic_id} already has an assignee")

        if (
            existing_assignee
            and allow_takeover_from
            and existing_assignee == allow_takeover_from
            and existing_assignee != agent_id
        ):
            released = runtime.release_epic_assignment(
                epic_id,
                beads_root=beads_root,
                cwd=cwd,
                expected_assignee=allow_takeover_from,
                expected_hooked=runtime.has_issue_label(runtime.issue_labels(issue), label_hooked),
            )
            if not released:
                runtime.die(f"epic {epic_id} takeover failed; claim ownership changed")

        claim_result = runtime.run_bd_command(
            ["update", epic_id, "--claim"],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if getattr(claim_result, "returncode", 1) != 0:
            refreshed = runtime.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
            assignee = None
            if refreshed:
                candidate_assignee = refreshed[0].get("assignee")
                if isinstance(candidate_assignee, str) and candidate_assignee.strip():
                    assignee = candidate_assignee.strip()
            if assignee != agent_id:
                runtime.die(f"epic {epic_id} already has an assignee")

        update_args = [
            "update",
            epic_id,
            "--status",
            "in_progress",
            "--add-label",
            runtime.issue_label(label_hooked),
        ]
        if runtime.is_standalone_changeset_without_epic_label(
            issue, beads_root=beads_root, cwd=cwd
        ):
            update_args.extend(["--add-label", runtime.issue_label(label_epic)])
        for attempt in range(2):
            runtime.run_bd_command(
                update_args,
                beads_root=beads_root,
                cwd=cwd,
                allow_failure=True,
            )
            refreshed = runtime.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
            if not refreshed:
                continue
            updated = refreshed[0]
            assignee = updated.get("assignee")
            if assignee != agent_id:
                runtime.die(f"epic {epic_id} claim failed; already assigned")
            if claim_is_complete(updated, claimant=agent_id):
                return updated
            if attempt == 0:
                continue
            runtime.die(
                f"epic {epic_id} claim failed; expected status=in_progress and label "
                f"{runtime.issue_label(label_hooked)}"
            )
        runtime.die(f"epic {epic_id} claim failed; unable to verify claimed state")
        return issue


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    runtime: AgentHooksRuntime,
    hook_slot_name: str,
) -> None:
    """Persist hook state for an agent bead in slot + description fields."""
    with runtime.issue_write_lock(agent_bead_id, beads_root):
        issues = runtime.run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
        if not issues:
            runtime.die(f"agent bead not found: {agent_bead_id}")
        runtime.run_bd_command(
            ["slot", "set", agent_bead_id, hook_slot_name, epic_id],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        runtime.update_description_fields_optimistic(
            agent_bead_id,
            fields={"hook_bead": epic_id},
            beads_root=beads_root,
            cwd=cwd,
        )
