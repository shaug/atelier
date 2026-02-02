"""Project policy helpers stored in Beads."""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import beads, editor, exec as exec_util
from .agent_home import AGENT_INSTRUCTIONS_FILENAME, AgentHome
from .io import die
from .models import ProjectConfig

ROLE_PLANNER = "planner"
ROLE_WORKER = "worker"
ROLE_BOTH = "both"
ROLE_VALUES = {ROLE_PLANNER, ROLE_WORKER}
ROLE_CHOICES = {ROLE_PLANNER, ROLE_WORKER, ROLE_BOTH}

COMBINED_MARKERS = {
    ROLE_PLANNER: "<!-- planner -->",
    ROLE_WORKER: "<!-- worker -->",
}


def normalize_role(value: str | None) -> str | None:
    """Normalize a role value or return None."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in ROLE_CHOICES:
        die("role must be one of: planner, worker, both")
    return normalized


def normalize_policy_text(value: str | None) -> str:
    """Normalize policy text for comparisons."""
    if not value:
        return ""
    return value.rstrip("\n")


def build_combined_policy(
    planner_text: str, worker_text: str
) -> tuple[str, bool]:
    """Return combined policy text and whether it contains split markers."""
    planner_text = normalize_policy_text(planner_text)
    worker_text = normalize_policy_text(worker_text)
    if planner_text and worker_text and planner_text != worker_text:
        combined = "\n".join(
            [
                COMBINED_MARKERS[ROLE_PLANNER],
                planner_text,
                "",
                COMBINED_MARKERS[ROLE_WORKER],
                worker_text,
                "",
            ]
        ).rstrip("\n")
        return combined, True
    combined = planner_text or worker_text
    return combined, False


def split_combined_policy(text: str) -> dict[str, str] | None:
    """Split combined policy text into role sections when markers are present."""
    lines = text.splitlines()
    marker_map = {value: key for key, value in COMBINED_MARKERS.items()}
    current: str | None = None
    sections: dict[str, list[str]] = {}
    found_marker = False
    for line in lines:
        key = marker_map.get(line.strip())
        if key:
            if current is not None:
                sections[current] = sections.get(current, [])
            current = key
            sections.setdefault(current, [])
            found_marker = True
            continue
        if current is not None:
            sections[current].append(line)
    if not found_marker:
        return None
    result: dict[str, str] = {}
    for role, collected in sections.items():
        result[role] = "\n".join(collected).strip("\n")
    return result


def edit_policy_text(
    initial_text: str, *, project_config: ProjectConfig, cwd: Path
) -> str:
    """Open a temp file in the editor and return the edited text."""
    editor_cmd = editor.resolve_editor_command(project_config, role="edit")
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as handle:
        handle.write(initial_text.rstrip("\n") + ("\n" if initial_text else ""))
        temp_path = Path(handle.name)
    try:
        exec_util.run_command([*editor_cmd, str(temp_path)], cwd=cwd)
        return temp_path.read_text(encoding="utf-8").rstrip("\n")
    finally:
        temp_path.unlink(missing_ok=True)


def _policy_block(role: str, body: str) -> str:
    start = f"<!-- ATELIER_POLICY_START role:{role} -->"
    end = f"<!-- ATELIER_POLICY_END role:{role} -->"
    title = f"## Project Policy ({role})"
    body_text = normalize_policy_text(body)
    return "\n".join([start, title, "", body_text, end]).rstrip("\n")


def apply_policy_block(content: str, *, role: str, body: str | None) -> str:
    """Insert or update the policy block in AGENTS.md content."""
    start = f"<!-- ATELIER_POLICY_START role:{role} -->"
    end = f"<!-- ATELIER_POLICY_END role:{role} -->"
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end), re.DOTALL
    )
    body_text = normalize_policy_text(body)
    if not body_text:
        updated = pattern.sub("", content)
        return updated.rstrip("\n") + "\n"
    block = _policy_block(role, body_text)
    if pattern.search(content):
        updated = pattern.sub(block, content)
        return updated.rstrip("\n") + "\n"
    content = content.rstrip("\n")
    if content:
        content += "\n\n"
    content += block
    return content.rstrip("\n") + "\n"


def sync_agent_home_policy(
    agent: AgentHome,
    *,
    role: str,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Ensure the agent home AGENTS.md includes the current policy."""
    if not isinstance(agent.path, Path):
        return
    issues = beads.list_policy_beads(role, beads_root=beads_root, cwd=cwd)
    body = ""
    if issues:
        body = beads.extract_policy_body(issues[0])
    agents_path = agent.path / AGENT_INSTRUCTIONS_FILENAME
    if not agents_path.exists():
        return
    content = agents_path.read_text(encoding="utf-8")
    updated = apply_policy_block(content, role=role, body=body)
    if updated != content:
        agents_path.write_text(updated, encoding="utf-8")
