"""Workspace helpers for naming and environment setup."""

import os
from pathlib import Path
from typing import Mapping

from .io import die


def workspace_environment(
    project_enlistment: str,
    workspace_branch: str,
    workspace_dir: Path,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build environment variables for workspace-aware subprocesses."""
    env = dict(base_env or os.environ)
    env["ATELIER_WORKSPACE"] = workspace_branch
    env["ATELIER_PROJECT"] = project_enlistment
    env["ATELIER_WORKSPACE_DIR"] = str(workspace_dir)
    return env


def workspace_identifier(project_enlistment: str, workspace_branch: str) -> str:
    """Build the stable workspace identifier string."""
    enlistment = project_enlistment
    branch = workspace_branch.lstrip("/")
    return f"atelier:{enlistment}:{branch}"


def workspace_session_identifier(
    project_enlistment: str, workspace_branch: str, workspace_uid: str | None = None
) -> str:
    """Build the workspace session identifier string."""
    base = workspace_identifier(project_enlistment, workspace_branch)
    if workspace_uid:
        return f"{base}:{workspace_uid}"
    return base


def workspace_candidate_branches(name: str, branch_prefix: str, raw: bool) -> list[str]:
    """Generate candidate branch names for a workspace lookup."""
    if raw:
        return [name]
    if branch_prefix and name.startswith(branch_prefix):
        return [name]
    candidates = []
    prefixed = f"{branch_prefix}{name}"
    if prefixed:
        candidates.append(prefixed)
    if name and name not in candidates:
        candidates.append(name)
    return candidates


def normalize_workspace_name(value: str) -> str:
    """Normalize and validate workspace branch input."""
    raw = value.strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        die("workspace branch must not be an absolute path")
    if ".." in Path(normalized).parts:
        die("workspace branch cannot contain '..'")
    return normalized
