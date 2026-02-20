"""Beads CLI helpers for Atelier."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import changesets, messages
from .external_tickets import (
    ExternalTicketRef,
    external_ticket_payload,
    normalize_external_ticket_entry,
)
from .io import die

POLICY_LABEL = "at:policy"
POLICY_SCOPE_LABEL = "scope:project"
EXTERNAL_TICKETS_KEY = "external_tickets"
HOOK_SLOT_NAME = "hook"
ATELIER_CUSTOM_TYPES = ("agent", "policy")
ATELIER_ISSUE_PREFIX = "at"
_AGENT_ISSUE_TYPE = "agent"
_FALLBACK_ISSUE_TYPE = "task"
_ISSUE_TYPE_CACHE: dict[Path, set[str]] = {}


@dataclass(frozen=True)
class ChangesetSummary:
    total: int
    ready: int
    merged: int
    abandoned: int
    remaining: int

    @property
    def ready_to_close(self) -> bool:
        return self.total > 0 and self.remaining == 0

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "ready": self.ready,
            "merged": self.merged,
            "abandoned": self.abandoned,
            "remaining": self.remaining,
        }


def beads_env(beads_root: Path) -> dict[str, str]:
    """Return an environment mapping with BEADS_DIR set."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_root)
    agent_id = env.get("ATELIER_AGENT_ID")
    if agent_id:
        env.setdefault("BD_ACTOR", agent_id)
        env.setdefault("BEADS_AGENT_NAME", agent_id)
    return env


def run_bd_command(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    allow_failure: bool = False,
    daemon: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a bd command and return the CompletedProcess.

    Raises a user-facing error when bd is missing or returns a non-zero status
    unless allow_failure is True.
    """
    cmd = ["bd", *args]
    if not daemon and "--no-daemon" not in cmd:
        cmd.append("--no-daemon")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=beads_env(beads_root),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        die("missing required command: bd")
    if result.returncode != 0 and not allow_failure:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"command failed: {' '.join(cmd)}"
        if detail:
            message = f"{message}\n{detail}"
        die(message)
    return result


def run_bd_json(
    args: list[str], *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """Run a bd command with --json and return parsed output."""
    cmd = list(args)
    if "--json" not in cmd:
        cmd.append("--json")
    result = run_bd_command(cmd, beads_root=beads_root, cwd=cwd)
    raw = result.stdout.strip() if result.stdout else ""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"failed to parse bd json output: {exc}")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def prime_addendum(*, beads_root: Path, cwd: Path) -> str | None:
    """Return `bd prime --full` markdown without failing the caller."""
    try:
        result = subprocess.run(
            ["bd", "prime", "--full", "--no-daemon"],
            cwd=cwd,
            env=beads_env(beads_root),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _parse_types_payload(raw: str) -> dict[str, object] | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None


def _extract_issue_types(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    types: set[str] = set()
    for key in ("core_types", "custom_types", "types"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name:
                    types.add(name)
            elif isinstance(item, str) and item:
                types.add(item)
    return types


def _list_issue_types(*, beads_root: Path, cwd: Path) -> set[str]:
    cached = _ISSUE_TYPE_CACHE.get(beads_root)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["bd", "types", "--json", "--no-daemon"],
            cwd=cwd,
            env=beads_env(beads_root),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        types = {_FALLBACK_ISSUE_TYPE}
        _ISSUE_TYPE_CACHE[beads_root] = types
        return types
    if result.returncode != 0:
        types = {_FALLBACK_ISSUE_TYPE}
        _ISSUE_TYPE_CACHE[beads_root] = types
        return types
    payload = _parse_types_payload(result.stdout or "")
    types = _extract_issue_types(payload)
    if not types:
        types = {_FALLBACK_ISSUE_TYPE}
    _ISSUE_TYPE_CACHE[beads_root] = types
    return types


def _agent_issue_type(*, beads_root: Path, cwd: Path) -> str:
    types = _list_issue_types(beads_root=beads_root, cwd=cwd)
    if _AGENT_ISSUE_TYPE in types:
        return _AGENT_ISSUE_TYPE
    return _FALLBACK_ISSUE_TYPE


def _parse_custom_types(value: str | None) -> list[str]:
    if not value:
        return []
    entries = []
    seen = set()
    for part in value.split(","):
        entry = part.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        entries.append(entry)
    return entries


def ensure_atelier_store(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure the Atelier Beads store exists with the expected prefix."""
    if beads_root.exists():
        return False
    run_bd_command(
        ["init", "--prefix", ATELIER_ISSUE_PREFIX, "--quiet"],
        beads_root=beads_root,
        cwd=cwd,
    )
    return True


def _current_issue_prefix(*, beads_root: Path, cwd: Path) -> str:
    result = run_bd_command(
        ["config", "get", "issue_prefix", "--json"], beads_root=beads_root, cwd=cwd
    )
    payload = _parse_types_payload(result.stdout or "")
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str):
            return value.strip()
    return ""


def ensure_issue_prefix(
    prefix: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> bool:
    """Ensure Beads uses the expected issue prefix."""
    expected = prefix.strip().lower()
    if not expected:
        return False
    current = _current_issue_prefix(beads_root=beads_root, cwd=cwd)
    if current == expected:
        return False
    run_bd_command(
        ["config", "set", "issue_prefix", expected], beads_root=beads_root, cwd=cwd
    )
    # Keep existing issue ids aligned with configured prefix.
    run_bd_command(
        ["rename-prefix", f"{expected}-", "--repair"], beads_root=beads_root, cwd=cwd
    )
    return True


def ensure_atelier_issue_prefix(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure Atelier uses the canonical issue prefix."""
    return ensure_issue_prefix(ATELIER_ISSUE_PREFIX, beads_root=beads_root, cwd=cwd)


def ensure_custom_types(
    required: list[str],
    *,
    beads_root: Path,
    cwd: Path,
) -> bool:
    """Ensure the Beads config includes required custom issue types."""
    required_clean = []
    seen = set()
    for entry in required:
        value = entry.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        required_clean.append(value)
    if not required_clean:
        return False
    result = run_bd_command(
        ["config", "get", "types.custom", "--json"],
        beads_root=beads_root,
        cwd=cwd,
    )
    payload = _parse_types_payload(result.stdout or "")
    current_value = ""
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str):
            current_value = value
    existing = _parse_custom_types(current_value)
    missing = [entry for entry in required_clean if entry not in existing]
    if not missing:
        return False
    updated = ",".join([*existing, *missing])
    run_bd_command(
        ["config", "set", "types.custom", updated], beads_root=beads_root, cwd=cwd
    )
    _ISSUE_TYPE_CACHE.pop(beads_root, None)
    return True


def ensure_atelier_types(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure Atelier-required custom issue types are configured."""
    return ensure_custom_types(
        list(ATELIER_CUSTOM_TYPES), beads_root=beads_root, cwd=cwd
    )


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def summarize_changesets(
    changesets: list[dict[str, object]],
    *,
    ready: list[dict[str, object]] | None = None,
) -> ChangesetSummary:
    """Return a summary of changeset lifecycle counts."""
    ready_count = len(ready) if ready is not None else 0
    merged = 0
    abandoned = 0
    for issue in changesets:
        labels = _issue_labels(issue)
        if "cs:merged" in labels:
            merged += 1
        if "cs:abandoned" in labels:
            abandoned += 1
    total = len(changesets)
    remaining = max(total - merged - abandoned, 0)
    return ChangesetSummary(
        total=total,
        ready=ready_count,
        merged=merged,
        abandoned=abandoned,
        remaining=remaining,
    )


def list_child_changesets(
    parent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List direct child changesets for a parent issue."""
    args = ["list", "--parent", parent_id, "--label", "at:changeset"]
    if include_closed:
        args.append("--all")
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_descendant_changesets(
    parent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List descendant changesets (children + deeper descendants)."""
    descendants: list[dict[str, object]] = []
    seen: set[str] = set()
    queue = [parent_id]
    while queue:
        current = queue.pop(0)
        children = list_child_changesets(
            current,
            beads_root=beads_root,
            cwd=cwd,
            include_closed=include_closed,
        )
        for issue in children:
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            if issue_id in seen:
                continue
            seen.add(issue_id)
            descendants.append(issue)
            queue.append(issue_id)
    return descendants


def _normalize_description(description: str | None) -> str:
    if not description:
        return ""
    return description.rstrip("\n")


def _parse_description_fields(description: str | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not description:
        return fields
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def parse_description_fields(description: str | None) -> dict[str, str]:
    """Parse key/value fields from a bead description."""
    return _parse_description_fields(description)


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


def _slot_show_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str | None:
    result = run_bd_command(
        ["slot", "show", agent_bead_id, "--json"],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip() if result.stdout else ""
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
    beads_root: Path,
    cwd: Path,
) -> None:
    run_bd_command(
        ["slot", "set", agent_bead_id, HOOK_SLOT_NAME, epic_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )


def get_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str | None:
    """Return the currently hooked epic id for an agent bead."""
    slot_hook = _slot_show_hook(agent_bead_id, beads_root=beads_root, cwd=cwd)
    if slot_hook:
        return slot_hook
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return None
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )
    hook = _normalize_hook_value(fields.get("hook_bead"))
    if hook:
        _slot_set_hook(agent_bead_id, hook, beads_root=beads_root, cwd=cwd)
    return hook


def workspace_label(root_branch: str) -> str:
    """Return the workspace label for a root branch."""
    return f"workspace:{root_branch}"


def external_label(provider: str) -> str:
    """Return the external ticket label for a provider."""
    return f"ext:{provider}"


def policy_role_label(role: str) -> str:
    """Return the policy role label."""
    return f"role:{role}"


def extract_workspace_root_branch(issue: dict[str, object]) -> str | None:
    """Extract the workspace root branch from a bead."""
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )
    root_branch = fields.get("workspace.root_branch")
    if root_branch:
        return root_branch
    labels = issue.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, str) and label.startswith("workspace:"):
                return label[len("workspace:") :]
    return None


def extract_worktree_path(issue: dict[str, object]) -> str | None:
    """Extract the worktree path from a bead description."""
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )
    worktree_path = fields.get("worktree_path")
    if worktree_path:
        return worktree_path
    return None


def parse_external_tickets(description: str | None) -> list[ExternalTicketRef]:
    """Parse external ticket references from a description."""
    if not description:
        return []
    fields = _parse_description_fields(description)
    tickets_raw = fields.get(EXTERNAL_TICKETS_KEY)
    if not tickets_raw or tickets_raw.lower() == "null":
        return []
    try:
        payload = json.loads(tickets_raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickets: list[ExternalTicketRef] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        normalized = normalize_external_ticket_entry(entry)
        if normalized is None:
            continue
        tickets.append(normalized)
    return tickets


def list_epics_by_workspace_label(
    root_branch: str, *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """List epic beads with the workspace label."""
    return run_bd_json(
        ["list", "--label", "at:epic", "--label", workspace_label(root_branch)],
        beads_root=beads_root,
        cwd=cwd,
    )


def find_epics_by_root_branch(
    root_branch: str, *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """Find epic beads by root branch label or description."""
    issues = list_epics_by_workspace_label(root_branch, beads_root=beads_root, cwd=cwd)
    if issues:
        return issues
    issues = run_bd_json(
        ["list", "--label", "at:epic"],
        beads_root=beads_root,
        cwd=cwd,
    )
    return [
        issue for issue in issues if extract_workspace_root_branch(issue) == root_branch
    ]


def update_workspace_root_branch(
    epic_id: str,
    root_branch: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the workspace root branch field + label for an epic."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    current = extract_workspace_root_branch(issue)
    if current and current != root_branch and not allow_override:
        die("workspace root branch already set; override not permitted")

    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="workspace.root_branch",
        value=root_branch,
    )
    label = workspace_label(root_branch)
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
    labels = [label for label in labels if isinstance(label, str)]
    remove_labels = [
        existing
        for existing in labels
        if existing.startswith("workspace:") and existing != label
    ]

    if label not in labels or remove_labels:
        args = ["update", epic_id]
        if label not in labels:
            args.extend(["--add-label", label])
        for existing in remove_labels:
            args.extend(["--remove-label", existing])
        run_bd_command(args, beads_root=beads_root, cwd=cwd)

    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_workspace_parent_branch(
    epic_id: str,
    parent_branch: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the workspace parent branch field for an epic."""
    if not parent_branch:
        die("parent branch must not be empty")
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )
    current = fields.get("workspace.parent_branch")
    if current and current.lower() != "null" and current != parent_branch:
        if not allow_override:
            die("workspace parent branch already set; override not permitted")
    if current == parent_branch:
        return issue
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="workspace.parent_branch",
        value=parent_branch,
    )
    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_worktree_path(
    epic_id: str,
    worktree_path: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the worktree_path field for an epic."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    current = extract_worktree_path(issue)
    if current and current != worktree_path and not allow_override:
        die("worktree path already set; override not permitted")
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="worktree_path",
        value=worktree_path,
    )
    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_changeset_branch_metadata(
    changeset_id: str,
    *,
    root_branch: str | None,
    parent_branch: str | None,
    work_branch: str | None,
    root_base: str | None = None,
    parent_base: str | None = None,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update branch lineage metadata fields for a changeset."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )

    def normalize(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "null":
            return None
        return cleaned

    updated = description if isinstance(description, str) else ""
    changed = False

    def apply(key: str, value: str | None) -> None:
        nonlocal updated, changed
        normalized = normalize(value)
        if normalized is None:
            return
        current = normalize(fields.get(key))
        if current and current != normalized and not allow_override:
            die(f"{key} already set; override not permitted")
        if current == normalized:
            return
        updated = _update_description_field(updated, key=key, value=normalized)
        changed = True

    apply("changeset.root_branch", root_branch)
    apply("changeset.parent_branch", parent_branch)
    apply("changeset.work_branch", work_branch)
    apply("changeset.root_base", root_base)
    apply("changeset.parent_base", parent_base)

    if changed:
        _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)
        refreshed = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
        return refreshed[0] if refreshed else issue
    return issue


def update_external_tickets(
    issue_id: str,
    tickets: list[ExternalTicketRef],
    *,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Update external ticket references and labels on a bead."""
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"issue not found: {issue_id}")
    issue = issues[0]
    payload = [external_ticket_payload(ticket) for ticket in tickets]
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key=EXTERNAL_TICKETS_KEY,
        value=serialized,
    )

    desired_labels = {external_label(ticket.provider) for ticket in tickets}
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
    labels = [label for label in labels if isinstance(label, str)]
    remove_labels = [
        label
        for label in labels
        if label.startswith("ext:") and label not in desired_labels
    ]
    add_labels = [label for label in desired_labels if label not in labels]
    if add_labels or remove_labels:
        args = ["update", issue_id]
        for label in add_labels:
            args.extend(["--add-label", label])
        for label in remove_labels:
            args.extend(["--remove-label", label])
        run_bd_command(args, beads_root=beads_root, cwd=cwd)

    _update_issue_description(issue_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def clear_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Clear the hooked epic id on the agent bead description."""
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"agent bead not found: {agent_bead_id}")
    run_bd_command(
        ["slot", "clear", agent_bead_id, HOOK_SLOT_NAME],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="hook_bead",
        value=None,
    )
    _update_issue_description(agent_bead_id, updated, beads_root=beads_root, cwd=cwd)


def list_policy_beads(
    role: str | None, *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """List project policy beads for the given role."""
    args = ["list", "--label", POLICY_LABEL, "--label", POLICY_SCOPE_LABEL]
    if role:
        args.extend(["--label", policy_role_label(role)])
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def extract_policy_body(issue: dict[str, object]) -> str:
    """Extract the policy body from a bead."""
    description = issue.get("description")
    if isinstance(description, str):
        return description.rstrip("\n")
    return ""


def create_policy_bead(
    role: str,
    body: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str:
    """Create a project policy bead for the role and return its id."""
    title = f"Project policy ({role})"
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body.rstrip("\n") + "\n" if body else "")
        temp_path = Path(handle.name)
    try:
        labels = ",".join([POLICY_LABEL, POLICY_SCOPE_LABEL, policy_role_label(role)])
        args = [
            "create",
            "--type",
            "policy",
            "--labels",
            labels,
            "--title",
            title,
            "--body-file",
            str(temp_path),
            "--silent",
        ]
        result = run_bd_command(args, beads_root=beads_root, cwd=cwd)
    finally:
        temp_path.unlink(missing_ok=True)
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create policy bead")
    return issue_id


def update_policy_bead(
    issue_id: str,
    body: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Update a project policy bead body."""
    _update_issue_description(issue_id, body, beads_root=beads_root, cwd=cwd)


def _update_description_field(
    description: str | None, *, key: str, value: str | None
) -> str:
    target = _normalize_description(description)
    lines = target.splitlines() if target else []
    updated: list[str] = []
    needle = f"{key}:"
    found = False
    for line in lines:
        if line.strip().startswith(needle):
            if not found:
                replacement = value if value is not None else "null"
                updated.append(f"{key}: {replacement}")
                found = True
            continue
        updated.append(line)
    if not found:
        replacement = value if value is not None else "null"
        updated.append(f"{key}: {replacement}")
    return "\n".join(updated).rstrip("\n") + "\n"


def _update_issue_description(
    issue_id: str,
    description: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = Path(handle.name)
    try:
        run_bd_command(
            ["update", issue_id, "--body-file", str(temp_path)],
            beads_root=beads_root,
            cwd=cwd,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def _create_issue_with_body(
    args: list[str],
    description: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = Path(handle.name)
    try:
        result = run_bd_command(
            [*args, "--body-file", str(temp_path), "--silent"],
            beads_root=beads_root,
            cwd=cwd,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create bead")
    return issue_id


def find_agent_bead(
    agent_id: str, *, beads_root: Path, cwd: Path
) -> dict[str, object] | None:
    """Find an agent bead by agent identity."""
    issues = run_bd_json(
        ["list", "--label", "at:agent", "--title-contains", agent_id],
        beads_root=beads_root,
        cwd=cwd,
    )
    return issues[0] if issues else None


def ensure_agent_bead(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    role: str | None = None,
) -> dict[str, object]:
    """Ensure an agent bead exists for the given identity."""
    existing = find_agent_bead(agent_id, beads_root=beads_root, cwd=cwd)
    if existing:
        return existing
    description = f"agent_id: {agent_id}\n"
    if role:
        description += f"role_type: {role}\n"
    issue_type = _agent_issue_type(beads_root=beads_root, cwd=cwd)
    result = run_bd_command(
        [
            "create",
            "--type",
            issue_type,
            "--labels",
            "at:agent",
            "--title",
            agent_id,
            "--description",
            description,
            "--silent",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create agent bead")
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if issues:
        return issues[0]
    return {"id": issue_id, "title": agent_id}


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_takeover_from: str | None = None,
) -> dict[str, object]:
    """Claim an epic by assigning it to the agent."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
    if "at:draft" in labels:
        die(f"epic {epic_id} is marked as draft")
    existing_assignee = issue.get("assignee")
    if (
        existing_assignee
        and existing_assignee != agent_id
        and existing_assignee != allow_takeover_from
    ):
        die(f"epic {epic_id} already has an assignee")
    run_bd_command(
        [
            "update",
            epic_id,
            "--assignee",
            agent_id,
            "--status",
            "hooked",
            "--add-label",
            "at:hooked",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if refreshed:
        updated = refreshed[0]
        assignee = updated.get("assignee")
        if assignee != agent_id:
            die(f"epic {epic_id} claim failed; already assigned")
        return updated
    return issue


def epic_changeset_summary(
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> ChangesetSummary:
    """Summarize changesets under an epic."""
    changesets = list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=cwd,
        include_closed=True,
    )
    return summarize_changesets(changesets)


def close_epic_if_complete(
    epic_id: str,
    agent_bead_id: str | None,
    *,
    beads_root: Path,
    cwd: Path,
    confirm: Callable[[ChangesetSummary], bool] | None = None,
) -> bool:
    """Close an epic and clear hook if all changesets are complete."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return False
    issue = issues[0]
    labels = _issue_labels(issue)
    is_standalone_changeset = "at:changeset" in labels and (
        "cs:merged" in labels or "cs:abandoned" in labels
    )
    summary = epic_changeset_summary(epic_id, beads_root=beads_root, cwd=cwd)
    if not is_standalone_changeset and not summary.ready_to_close:
        return False
    if confirm is not None and not confirm(summary):
        return False
    run_bd_command(["close", epic_id], beads_root=beads_root, cwd=cwd)
    if agent_bead_id:
        clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=cwd)
    return True


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Store the hooked epic id on the agent bead description."""
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"agent bead not found: {agent_bead_id}")
    run_bd_command(
        ["slot", "set", agent_bead_id, HOOK_SLOT_NAME, epic_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="hook_bead",
        value=epic_id,
    )
    _update_issue_description(agent_bead_id, updated, beads_root=beads_root, cwd=cwd)


def create_message_bead(
    *,
    subject: str,
    body: str,
    metadata: dict[str, object],
    assignee: str | None = None,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Create a message bead and return its data."""
    description = messages.render_message(metadata, body)
    args = [
        "create",
        "--type",
        "task",
        "--labels",
        "at:message,at:unread",
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = _create_issue_with_body(
        args, description, beads_root=beads_root, cwd=cwd
    )
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return issues[0] if issues else {"id": issue_id, "title": subject}


def list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List message beads assigned to the agent."""
    args = ["list", "--label", "at:message", "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", "at:unread"])
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_queue_messages(
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None = None,
    unclaimed_only: bool = True,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List queued message beads, optionally filtered by queue name."""
    args = ["list", "--label", "at:message"]
    if unread_only:
        args.extend(["--label", "at:unread"])
    issues = run_bd_json(args, beads_root=beads_root, cwd=cwd)
    matches: list[dict[str, object]] = []
    for issue in issues:
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        queue_name = payload.metadata.get("queue")
        if not isinstance(queue_name, str) or not queue_name.strip():
            continue
        if queue is not None and queue_name != queue:
            continue
        claimed_by = payload.metadata.get("claimed_by")
        if unclaimed_only and isinstance(claimed_by, str) and claimed_by.strip():
            continue
        enriched = dict(issue)
        enriched["queue"] = queue_name
        enriched["claimed_by"] = claimed_by
        matches.append(enriched)
    return matches


def claim_queue_message(
    message_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None = None,
) -> dict[str, object]:
    """Claim a queued message bead by setting claimed metadata."""
    issues = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"message not found: {message_id}")
    issue = issues[0]
    description = issue.get("description")
    payload = messages.parse_message(
        description if isinstance(description, str) else ""
    )
    queue_name = payload.metadata.get("queue")
    if not isinstance(queue_name, str) or not queue_name.strip():
        die(f"message {message_id} is not in a queue")
    if queue is not None and queue_name != queue:
        die(f"message {message_id} is not in queue {queue!r}")
    claimed_by = payload.metadata.get("claimed_by")
    if isinstance(claimed_by, str) and claimed_by.strip():
        die(f"message {message_id} already claimed by {claimed_by}")
    payload.metadata["claimed_by"] = agent_id
    payload.metadata["claimed_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    updated = messages.render_message(payload.metadata, payload.body)
    _update_issue_description(message_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def mark_message_read(
    message_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Mark a message bead as read."""
    run_bd_command(
        ["update", message_id, "--remove-label", "at:unread"],
        beads_root=beads_root,
        cwd=cwd,
    )


def update_changeset_integrated_sha(
    changeset_id: str,
    integrated_sha: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the integrated SHA field for a changeset bead."""
    if not integrated_sha:
        die("integrated sha must not be empty")
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(
        description if isinstance(description, str) else ""
    )
    current = fields.get("changeset.integrated_sha")
    if current and current.lower() != "null" and current != integrated_sha:
        if not allow_override:
            die("changeset integrated sha already set; override not permitted")
    if current == integrated_sha:
        return issue
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="changeset.integrated_sha",
        value=integrated_sha,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_changeset_review(
    changeset_id: str,
    metadata: changesets.ReviewMetadata,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Update review metadata fields for a changeset bead."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = changesets.apply_review_metadata(
        description if isinstance(description, str) else "",
        metadata,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)


def update_changeset_review_feedback_cursor(
    changeset_id: str,
    latest_feedback_at: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Persist the latest handled review feedback timestamp on a changeset."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="review.last_feedback_seen_at",
        value=latest_feedback_at,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)
