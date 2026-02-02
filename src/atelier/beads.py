"""Beads CLI helpers for Atelier."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import changesets, exec, messages
from .io import die

POLICY_LABEL = "at:policy"
POLICY_SCOPE_LABEL = "scope:project"


def beads_env(beads_root: Path) -> dict[str, str]:
    """Return an environment mapping with BEADS_DIR set."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_root)
    return env


def run_bd_command(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a bd command and return the CompletedProcess.

    Raises a user-facing error when bd is missing or returns a non-zero status
    unless allow_failure is True.
    """
    cmd = ["bd", *args]
    result = exec.try_run_command(cmd, cwd=cwd, env=beads_env(beads_root))
    if result is None:
        die("missing required command: bd")
    if result.returncode != 0 and not allow_failure:
        die(f"command failed: {' '.join(cmd)}")
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


def workspace_label(root_branch: str) -> str:
    """Return the workspace label for a root branch."""
    return f"workspace:{root_branch}"


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
        args = [
            "create",
            "--type",
            "policy",
            "--label",
            POLICY_LABEL,
            "--label",
            POLICY_SCOPE_LABEL,
            "--label",
            policy_role_label(role),
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
        description += f"role: {role}\n"
    result = run_bd_command(
        [
            "create",
            "--type",
            "agent",
            "--label",
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
    if existing_assignee and existing_assignee != agent_id:
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
        "--label",
        "at:message",
        "--label",
        "at:unread",
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
