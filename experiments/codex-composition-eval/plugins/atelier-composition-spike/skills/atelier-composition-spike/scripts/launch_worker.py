#!/usr/bin/env python3
"""Launch one Codex worker and supervise its one-shot host review request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def digest(value: str) -> str:
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


def render_prompt(case_root: Path, transport: Path, codex_version: str) -> str:
    """Render the shared worker task with only this case's input paths."""
    template = Path(__file__).resolve().parents[1] / "references" / "worker-task.md"
    replacements = {
        "{{CASE_ROOT}}": str(case_root),
        "{{INVOCATION_PATH}}": str(case_root / "invocation.json"),
        "{{FIXTURE_PATH}}": str(case_root / "fixture.json"),
        "{{TRANSPORT_PATH}}": str(transport),
        "{{REVIEW_LAUNCHER}}": str(Path(__file__).with_name("launch_reviewer.py").resolve()),
        "{{CODEX_VERSION}}": codex_version,
    }
    prompt = template.read_text()
    for source, target in replacements.items():
        prompt = prompt.replace(source, target)
    return prompt


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-root", required=True, type=Path)
    parser.add_argument("--transport", required=True, type=Path)
    parser.add_argument("--codex-executable", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Run a worker and service at most one causally bound review request."""
    args = parse_args()
    case_root = args.case_root.resolve()
    transport = args.transport.resolve()
    codex_executable = args.codex_executable.resolve()
    version = subprocess.run(
        [str(codex_executable), "--version"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    prompt = render_prompt(case_root, transport, version)
    raw_events = case_root / "codex-events.jsonl"
    final_output = case_root / "codex-final.txt"
    stderr_path = case_root / "codex-stderr.txt"
    command = [
        str(codex_executable),
        "exec",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(case_root / "repository"),
        "--add-dir",
        str(case_root),
        "--output-last-message",
        str(final_output),
        "-",
    ]
    plugins = subprocess.run(
        [str(codex_executable), "plugin", "list", "--json"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    review_launcher = Path(__file__).with_name("launch_reviewer.py").resolve()
    request_path = case_root / "review-request.json"
    atomic_write(
        case_root / "host-launch.json",
        {
            "command": command,
            "codex_executable_sha256": hashlib.sha256(codex_executable.read_bytes()).hexdigest(),
            "codex_version": version,
            "launched_at": datetime.now(UTC).isoformat(),
            "plugin_list": json.loads(plugins),
            "prompt_sha256": digest(prompt),
            "review_supervisor": {
                "kind": "one-shot-file-request",
                "launcher": str(review_launcher),
                "request_path": str(request_path),
            },
        },
    )
    review_serviced = False
    with (
        raw_events.open("x") as stdout_handle,
        stderr_path.open("x") as stderr_handle,
    ):
        worker = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        assert worker.stdin is not None
        worker.stdin.write(prompt)
        worker.stdin.close()
        while worker.poll() is None:
            if request_path.is_file() and not review_serviced:
                request = read_object(request_path)
                review_input = Path(str(request["review_input"])).resolve()
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(review_launcher),
                        "host",
                        "--case-root",
                        str(case_root),
                        "--review-input",
                        str(review_input),
                        "--codex-executable",
                        str(codex_executable),
                        "--codex-version",
                        version,
                    ],
                    check=False,
                )
                atomic_write(
                    case_root / "review-complete.json",
                    {
                        "schema": "atelier.composition/review-complete/v1",
                        "request_id": request["request_id"],
                        "exit_code": completed.returncode,
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )
                review_serviced = True
            time.sleep(0.25)
    return worker.returncode


if __name__ == "__main__":
    raise SystemExit(main())
