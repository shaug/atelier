#!/usr/bin/env python3
"""Create a GitHub issue and print its metadata as JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Iterable, Sequence

FIELDS = ["number", "title", "body", "state", "url", "labels", "assignees", "author"]


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


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


def parse_labels(raw: str | None) -> list[str]:
    if raw is None:
        return []
    raw = raw.strip()
    if raw == "":
        return []
    return [label.strip() for label in raw.split(",") if label.strip()]


def issue_view(repo: str, issue_ref: str) -> str:
    fields = ",".join(FIELDS)
    return run_gh(["issue", "view", issue_ref, "--repo", repo, "--json", fields])


def last_non_empty_line(lines: Iterable[str]) -> str | None:
    candidate = None
    for line in lines:
        stripped = line.strip()
        if stripped:
            candidate = stripped
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repo in OWNER/REPO form")
    parser.add_argument("--title", required=True, help="Issue title")
    parser.add_argument("--body", required=True, help="Issue body")
    parser.add_argument(
        "--labels",
        default=None,
        help="Comma-separated labels to apply (optional)",
    )
    args = parser.parse_args()

    labels = parse_labels(args.labels)

    cmd = [
        "issue",
        "create",
        "--repo",
        args.repo,
        "--title",
        args.title,
        "--body",
        args.body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    output = run_gh(cmd)
    issue_ref = last_non_empty_line(output.splitlines())
    if not issue_ref:
        die("gh issue create returned no issue reference", 2)

    payload = issue_view(args.repo, issue_ref)
    json.loads(payload)
    print(payload)


if __name__ == "__main__":
    main()
