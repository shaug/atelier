"""Worker runtime profile helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import ProjectConfig
from ..runtime_profiles import RuntimeProfileName, normalize_runtime_profile

_BOUNDED_EVIDENCE_FILENAME = "bounded-runtime-evidence.json"
_BOUNDED_EVIDENCE_TOKEN_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_worker_runtime_profile(
    project_config: ProjectConfig,
    *,
    runtime_profile_override: object,
) -> RuntimeProfileName:
    """Resolve the worker runtime profile from config and CLI override."""
    selected = runtime_profile_override
    if selected is None:
        selected = project_config.runtime.worker.profile
    return normalize_runtime_profile(selected, source="runtime.worker.profile")


def worker_runtime_profile_contract(profile: RuntimeProfileName) -> str:
    """Return worker guidance for the selected runtime profile."""
    if profile == "trycycle-bounded":
        return (
            "Bounded worker contract: keep helper-session orchestration internal "
            "to this worker session, write convergence evidence, and fail closed "
            "if helper-session output cannot prove the assigned changeset stayed "
            "bounded to the requested contract."
        )
    return "Standard worker contract: follow the default Atelier single-changeset execution loop."


def bounded_runtime_evidence_path(
    agent_home_path: Path, *, iteration_token: str | None = None
) -> Path:
    """Return the evidence file path for bounded worker runs."""
    if iteration_token is None:
        return agent_home_path / _BOUNDED_EVIDENCE_FILENAME
    normalized_token = _BOUNDED_EVIDENCE_TOKEN_PATTERN.sub("-", iteration_token).strip("-")
    if not normalized_token:
        return agent_home_path / _BOUNDED_EVIDENCE_FILENAME
    stem = Path(_BOUNDED_EVIDENCE_FILENAME).stem
    suffix = Path(_BOUNDED_EVIDENCE_FILENAME).suffix
    return agent_home_path / f"{stem}-{normalized_token}{suffix}"


def clear_bounded_runtime_evidence(*, evidence_path: Path) -> None:
    """Remove any pre-existing bounded evidence file before a worker launch."""
    try:
        evidence_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def bounded_runtime_failure_reason(*, evidence_path: Path) -> str:
    """Return an explicit fail-closed reason for missing bounded evidence."""
    return (
        "bounded runtime convergence unproven: expected converged helper-session "
        f"evidence at {evidence_path}"
    )


def verify_bounded_runtime_evidence(*, evidence_path: Path) -> str | None:
    """Validate bounded worker evidence."""
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return bounded_runtime_failure_reason(evidence_path=evidence_path)
    except (OSError, json.JSONDecodeError):
        return bounded_runtime_failure_reason(evidence_path=evidence_path)
    if not isinstance(payload, dict):
        return bounded_runtime_failure_reason(evidence_path=evidence_path)
    status = payload.get("status")
    helper_session_id = payload.get("helper_session_id")
    if status != "converged":
        return bounded_runtime_failure_reason(evidence_path=evidence_path)
    if not isinstance(helper_session_id, str) or not helper_session_id.strip():
        return bounded_runtime_failure_reason(evidence_path=evidence_path)
    return None
