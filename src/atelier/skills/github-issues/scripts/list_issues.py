#!/usr/bin/env python3
"""List GitHub issues and print JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Sequence

FIELDS = [
    "number",
    "title",
    "body",
    "state",
    "url",
    "labels",
    "updatedAt",
    "stateReason",
]


def run_gh(args: Sequence[str]) -> str:
    result = subprocess.run(
        ["gh", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        elif result.stdout:
            sys.stderr.write(result.stdout)
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repo in OWNER/REPO form")
    parser.add_argument(
        "--state",
        default="open",
        choices=("open", "closed", "all"),
        help="Issue state filter",
    )
    parser.add_argument("--search", help="Search query")
    parser.add_argument("--limit", type=int, help="Maximum number of issues")
    args = parser.parse_args()

    fields = ",".join(FIELDS)
    cmd = [
        "issue",
        "list",
        "--repo",
        args.repo,
        "--json",
        fields,
        "--state",
        args.state,
    ]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    if args.search:
        cmd.extend(["--search", args.search])

    payload = run_gh(cmd)
    json.loads(payload)
    print(payload)


if __name__ == "__main__":
    main()
