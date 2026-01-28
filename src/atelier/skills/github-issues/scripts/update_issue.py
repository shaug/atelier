#!/usr/bin/env python3
"""Update GitHub issue fields and print metadata as JSON."""

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


def parse_labels(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return []
    return [label.strip() for label in raw.split(",") if label.strip()]


def issue_view(repo: str, issue_ref: str) -> dict:
    fields = ",".join(FIELDS)
    payload = run_gh(["issue", "view", issue_ref, "--repo", repo, "--json", fields])
    return json.loads(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repo in OWNER/REPO form")
    parser.add_argument("--issue", required=True, help="Issue number or URL")
    parser.add_argument("--title", default=None, help="New issue title")
    parser.add_argument("--body", default=None, help="New issue body")
    parser.add_argument(
        "--labels",
        default=None,
        help="Comma-separated labels to set exactly (empty string clears)",
    )
    args = parser.parse_args()

    desired_labels = parse_labels(args.labels)

    to_add: list[str] = []
    to_remove: list[str] = []

    if desired_labels is not None:
        current = issue_view(args.repo, args.issue)
        current_labels = [label["name"] for label in current.get("labels", [])]
        current_set = set(current_labels)
        desired_set = set(desired_labels)
        to_add = sorted(desired_set - current_set)
        to_remove = sorted(current_set - desired_set)

    has_changes = args.title is not None or args.body is not None or to_add or to_remove

    if has_changes:
        cmd = ["issue", "edit", args.issue, "--repo", args.repo]
        if args.title is not None:
            cmd.extend(["--title", args.title])
        if args.body is not None:
            cmd.extend(["--body", args.body])
        for label in to_add:
            cmd.extend(["--add-label", label])
        for label in to_remove:
            cmd.extend(["--remove-label", label])
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
