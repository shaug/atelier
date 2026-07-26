#!/usr/bin/env python3
"""Durable checkpoint command for the Atelier composition experiment."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType


def load_validator(skill_root: Path) -> ModuleType:
    """Load the validator owned by the installed Agent Scripts skill."""
    path = skill_root / "references" / "delegated-execution" / "validate.py"
    spec = importlib.util.spec_from_file_location(
        "agent_scripts_delegated_validator",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Agent Scripts validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_object(path: Path) -> dict[str, object]:
    """Read one JSON object."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def atomic_write(path: Path, value: dict[str, object]) -> None:
    """Persist one JSON object with fsync and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def response_for(
    request: dict[str, object],
    decision: str,
    reason: str | None,
    *,
    acknowledged_candidate_sha: str | None = None,
) -> dict[str, object]:
    """Build one checkpoint response."""
    prior = str(request["continuation_token"])
    if decision == "allow":
        material = f"{prior}:{request['sequence']}:{request['phase']}:{request['action']}"
        continuation = hashlib.sha256(material.encode()).hexdigest()
    else:
        continuation = prior
    return {
        "schema": "agent-scripts.implement-ticket/checkpoint-response/v1",
        "invocation_id": request["invocation_id"],
        "request_sequence": request["sequence"],
        "prior_continuation_token": prior,
        "continuation_token": continuation,
        "decision": decision,
        "reason": reason,
        "acknowledged_candidate_sha": acknowledged_candidate_sha,
    }


def binding_errors(
    state: dict[str, object],
    request: dict[str, object],
) -> list[str]:
    """Compare one valid request with its immutable invocation fence."""
    errors: list[str] = []
    comparisons = (
        ("invocation_id", request["invocation_id"]),
        ("capability", request["capability"]),
        ("ticket_observation", request["ticket_observation"]),
    )
    for field, actual in comparisons:
        if state[field] != actual:
            errors.append(f"$.{field}: does not match checkpoint invocation")
    candidate = request["candidate"]
    if candidate is None:
        return errors
    assert isinstance(candidate, dict)
    repository = state["repository"]
    assert isinstance(repository, dict)
    candidate_expectations = {
        "repository": repository["identity"],
        "remote_url": repository["remote_url"],
        "base_sha": repository["base_sha"],
    }
    for field, expected in candidate_expectations.items():
        if candidate[field] != expected:
            errors.append(f"$.candidate.{field}: does not match checkpoint invocation")
    return errors


def published_candidate_error(request: dict[str, object]) -> str | None:
    """Verify a publication checkpoint's exact reachable remote ref."""
    if request["phase"] != "candidate_published":
        return None
    candidate = request["candidate"]
    assert isinstance(candidate, dict)
    completed = subprocess.run(
        ["git", "ls-remote", str(candidate["remote_url"]), str(candidate["remote_ref"])],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return f"candidate remote verification failed: {completed.stderr.strip()}"
    fields = completed.stdout.split()
    if len(fields) < 2 or fields[0] != candidate["head_sha"]:
        return "candidate remote ref does not resolve to proposed head"
    return None


def handle(
    skill_root: Path,
    state_path: Path,
    request: dict[str, object],
) -> dict[str, object]:
    """Validate, fence, persist, and answer one checkpoint request."""
    validator = load_validator(skill_root)
    structural_errors = validator.validate("checkpoint-request", request)
    if structural_errors:
        raise ValueError("invalid checkpoint request: " + "; ".join(structural_errors))
    lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_object(state_path)
        immutable_errors = binding_errors(state, request)
        if immutable_errors:
            return response_for(
                request,
                "deny",
                "checkpoint invocation mismatch: " + "; ".join(immutable_errors),
            )
        allow_actions = set(state.get("allow_actions", []))
        deny_actions = set(state.get("deny_actions", []))
        action = str(request["action"])
        if action not in allow_actions:
            decision = "deny"
            reason = f"invocation authority excludes {action}"
        elif action in deny_actions:
            decision = "deny"
            reason = f"fixture policy denies {action}"
        else:
            decision = "allow"
            reason = None
        acknowledged = None
        if decision == "allow":
            publication_error = published_candidate_error(request)
            if publication_error is not None:
                decision = "deny"
                reason = publication_error
            elif request["phase"] == "candidate_published":
                candidate = request["candidate"]
                assert isinstance(candidate, dict)
                acknowledged = str(candidate["head_sha"])
        response = response_for(
            request,
            decision,
            reason,
            acknowledged_candidate_sha=acknowledged,
        )
        progress_errors = validator.validate_checkpoint_progress(
            state["last_sequence"],
            state["continuation_token"],
            request,
            response,
        )
        if progress_errors:
            return response_for(
                request,
                "deny",
                "checkpoint state mismatch: " + "; ".join(progress_errors),
            )
        if decision == "allow":
            ledger = list(state["ledger"])
            ledger.append(
                {
                    "invocation_id": request["invocation_id"],
                    "sequence": request["sequence"],
                    "phase": request["phase"],
                    "action": request["action"],
                    "proposed_effect": request["proposed_effect"],
                    "candidate": request["candidate"],
                    "acknowledged_candidate_sha": response["acknowledged_candidate_sha"],
                }
            )
            state["last_sequence"] = request["sequence"]
            state["continuation_token"] = response["continuation_token"]
            state["ledger"] = ledger
            atomic_write(state_path, state)
        return response


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--implement-ticket-root", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Read one request from stdin and write one response to stdout."""
    args = parse_args()
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("checkpoint request must be an object")
        response = handle(
            args.implement_ticket_root.resolve(),
            args.state.resolve(),
            request,
        )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    json.dump(response, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
