#!/usr/bin/env python3
"""Request or host one isolated Codex review with durable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def digest_bytes(path: Path) -> str:
    """Return a SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_text(value: str) -> str:
    """Return a SHA-256 digest for text."""
    return hashlib.sha256(value.encode()).hexdigest()


def read_object(path: Path) -> dict[str, object]:
    """Read one JSON object."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def atomic_write(path: Path, value: object) -> None:
    """Write deterministic JSON with fsync and atomic replacement."""
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def render_prompt(review_input: Path, source: dict[str, object]) -> str:
    """Build a result-blind review prompt for one exact candidate."""
    return "\n".join(
        (
            "Act as an independent, read-only code reviewer in a fresh Codex process.",
            "Do not mutate files, refs, tickets, or external systems.",
            "Inspect the exact candidate described below using its candidate_git_dir.",
            "Verify the stated base and head before reviewing the complete committed diff.",
            "Review correctness, scope discipline, simplicity, and validation evidence.",
            "Treat any inability to inspect the exact candidate as a blocked verdict.",
            "Return only JSON matching the supplied output schema.",
            f"Review input path: {review_input}",
            "Authoritative review input:",
            json.dumps(source, indent=2, sort_keys=True),
        )
    )


def request_review(case_root: Path, review_input: Path) -> int:
    """Publish one review request and wait for its host-owned completion."""
    request_path = case_root / "review-request.json"
    completion_path = case_root / "review-complete.json"
    owned_outputs = (
        request_path,
        completion_path,
        case_root / "review-launch.json",
        case_root / "review-events.jsonl",
        case_root / "review-final.json",
        case_root / "review-stderr.txt",
    )
    if any(path.exists() for path in owned_outputs):
        raise ValueError("refusing to repair or repeat an existing review attempt")
    input_sha256 = digest_bytes(review_input)
    request_id = digest_text(f"{review_input.resolve()}:{input_sha256}")
    atomic_write(
        request_path,
        {
            "schema": "atelier.composition/review-request/v1",
            "request_id": request_id,
            "review_input": str(review_input.resolve()),
            "review_input_sha256": input_sha256,
            "requested_at": datetime.now(UTC).isoformat(),
        },
    )
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if completion_path.is_file():
            completion = read_object(completion_path)
            if completion.get("request_id") != request_id:
                raise ValueError("review completion does not match the request")
            return int(completion["exit_code"])
        time.sleep(0.25)
    raise TimeoutError("host did not complete the review request within 900 seconds")


def host_review(
    case_root: Path,
    review_input: Path,
    codex_executable: Path,
    codex_version: str,
) -> int:
    """Launch a fresh reviewer from the host side of the worker boundary."""
    expected_input = (case_root / "review-input.json").resolve()
    if review_input.resolve() != expected_input:
        raise ValueError("review input must be the case-owned review-input.json")
    input_sha256 = digest_bytes(review_input)
    expected_request_id = digest_text(f"{expected_input}:{input_sha256}")
    request = read_object(case_root / "review-request.json")
    if (
        request.get("schema") != "atelier.composition/review-request/v1"
        or request.get("request_id") != expected_request_id
        or request.get("review_input") != str(expected_input)
        or request.get("review_input_sha256") != input_sha256
    ):
        raise ValueError("review request does not bind the case-owned input")
    source = read_object(review_input)
    repository = Path(str(source["repository_path"])).resolve()
    candidate_git_dir = Path(str(source["candidate_git_dir"])).resolve()
    if (
        repository != (case_root / "repository").resolve()
        or not candidate_git_dir.is_relative_to(case_root)
        or not candidate_git_dir.is_dir()
    ):
        raise ValueError("review input escapes the case-owned repository boundary")
    prompt = render_prompt(review_input, source)
    schema = Path(__file__).resolve().parents[1] / "references" / "reviewer-output.schema.json"
    raw_events = case_root / "review-events.jsonl"
    final_output = case_root / "review-final.json"
    stderr_path = case_root / "review-stderr.txt"
    command = [
        str(codex_executable),
        "exec",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "--cd",
        str(repository),
        "--add-dir",
        str(case_root),
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(final_output),
        "-",
    ]
    atomic_write(
        case_root / "review-launch.json",
        {
            "command": command,
            "codex_executable_sha256": digest_bytes(codex_executable),
            "codex_version": codex_version,
            "launched_at": datetime.now(UTC).isoformat(),
            "prompt_sha256": digest_text(prompt),
            "request_id": request["request_id"],
            "review_input_sha256": digest_bytes(review_input),
            "schema_sha256": digest_bytes(schema),
        },
    )
    with (
        raw_events.open("x") as stdout_handle,
        stderr_path.open("x") as stderr_handle,
    ):
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )
    return completed.returncode


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request")
    request.add_argument("--case-root", required=True, type=Path)
    request.add_argument("--review-input", required=True, type=Path)
    host = commands.add_parser("host")
    host.add_argument("--case-root", required=True, type=Path)
    host.add_argument("--review-input", required=True, type=Path)
    host.add_argument("--codex-executable", required=True, type=Path)
    host.add_argument("--codex-version", required=True)
    return parser.parse_args()


def main() -> int:
    """Dispatch one review request or host launch."""
    args = parse_args()
    case_root = args.case_root.resolve()
    review_input = args.review_input.resolve()
    if args.command == "request":
        return request_review(case_root, review_input)
    return host_review(
        case_root,
        review_input,
        args.codex_executable.resolve(),
        args.codex_version,
    )


if __name__ == "__main__":
    raise SystemExit(main())
