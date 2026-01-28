#!/usr/bin/env python3
"""Close a GitHub issue and print metadata as JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Sequence

FIELDS = ["number", "title", "body", "state", "url", "labels", "assignees", "author"]


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
    parser.add_argument("--issue", required=True, help="Issue number or URL")
    parser.add_argument("--comment", default=None, help="Optional closing comment")
    parser.add_argument(
        "--reason",
        default=None,
        choices=("completed", "not planned"),
        help="Optional close reason",
    )
    args = parser.parse_args()

    cmd = ["issue", "close", args.issue, "--repo", args.repo]
    if args.comment is not None:
        cmd.extend(["--comment", args.comment])
    if args.reason is not None:
        cmd.extend(["--reason", args.reason])
    run_gh(cmd)

    payload = run_gh(
        [
            "issue",
            "view",
            args.issue,
            "--repo",
            args.repo,
            "--json",
            ",".join(FIELDS),
        ]
    )
    json.loads(payload)
    print(payload)


if __name__ == "__main__":
    main()
