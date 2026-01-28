#!/usr/bin/env python3
"""Read GitHub PR status and metadata using gh CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Iterable


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        if not message:
            message = f"Command failed: {' '.join(cmd)}"
        raise RuntimeError(message)
    return result.stdout


def run_json(cmd: list[str]) -> object:
    output = run(cmd)
    try:
        return json.loads(output) if output.strip() else None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(cmd)}") from exc


def find_latest_pr_number(repo: str, head: str) -> int | None:
    payload = run_json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--head",
            head,
            "--state",
            "all",
            "--json",
            "number",
        ]
    )
    if not payload:
        return None
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected gh output for PR list")
    numbers = sorted(
        {
            entry.get("number")
            for entry in payload
            if isinstance(entry, dict) and isinstance(entry.get("number"), int)
        }
    )
    return numbers[-1] if numbers else None


def read_pr(repo: str, number: int) -> dict[str, object]:
    payload = run_json(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,url,state,baseRefName,headRefName,title,body,labels,isDraft,mergedAt,closedAt,updatedAt,reviewDecision,mergeable",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected gh output for PR view")
    return payload


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Read GitHub PR status.")
    parser.add_argument("--repo", required=True, help="GitHub repo slug (owner/name)")
    parser.add_argument("--head", required=True, help="Head branch")
    args = parser.parse_args(list(argv))

    try:
        number = find_latest_pr_number(args.repo, args.head)
        if number is None:
            raise RuntimeError("No PR found for the head branch")
        payload = read_pr(args.repo, number)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
