#!/usr/bin/env python3
"""Update GitHub issue fields and print metadata as JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator, Sequence

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


@contextmanager
def issue_body_file(*, body: str | None, body_file: str | None) -> Iterator[str | None]:
    if body_file:
        yield body_file
        return
    if body is None:
        yield None
        return
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body)
        temp_path = Path(handle.name)
    try:
        yield str(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repo in OWNER/REPO form")
    parser.add_argument("--issue", required=True, help="Issue number or URL")
    parser.add_argument("--title", default=None, help="New issue title")
    body_group = parser.add_mutually_exclusive_group(required=False)
    body_group.add_argument("--body", default=None, help="New issue body")
    body_group.add_argument("--body-file", default=None, help="Path to new issue body file")
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

    body_supplied = args.body is not None or args.body_file is not None
    has_changes = args.title is not None or body_supplied or to_add or to_remove

    if has_changes:
        with issue_body_file(body=args.body, body_file=args.body_file) as new_body_file:
            cmd = ["issue", "edit", args.issue, "--repo", args.repo]
            if args.title is not None:
                cmd.extend(["--title", args.title])
            if new_body_file is not None:
                cmd.extend(["--body-file", new_body_file])
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
