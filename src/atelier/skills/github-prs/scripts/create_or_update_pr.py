#!/usr/bin/env python3
"""Create or update a GitHub PR for a head branch using gh CLI."""

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


def parse_labels(raw: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        label = item.strip()
        if not label or label in seen:
            continue
        labels.append(label)
        seen.add(label)
    return labels


def find_pr_number(repo: str, head: str) -> int | None:
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
            "open",
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
    return numbers[0] if numbers else None


def edit_labels(repo: str, number: int, desired: list[str]) -> None:
    payload = run_json(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "labels",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected gh output for PR view")
    labels = payload.get("labels") or []
    current = {
        entry.get("name") for entry in labels if isinstance(entry, dict) and entry.get("name")
    }
    desired_set = set(desired)
    to_add = sorted(desired_set - current)
    to_remove = sorted(current - desired_set)

    if not to_add and not to_remove:
        return

    cmd: list[str] = ["gh", "pr", "edit", str(number), "--repo", repo]
    for label in to_add:
        cmd.extend(["--add-label", label])
    for label in to_remove:
        cmd.extend(["--remove-label", label])
    run(cmd)


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
            "number,url,state,baseRefName,headRefName,title,body,labels,isDraft,mergedAt,closedAt,updatedAt",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected gh output for PR view")
    return payload


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Create or update a GitHub PR.")
    parser.add_argument("--repo", required=True, help="GitHub repo slug (owner/name)")
    parser.add_argument("--base", required=True, help="Base branch")
    parser.add_argument("--head", required=True, help="Head branch")
    parser.add_argument("--title", required=True, help="PR title")
    parser.add_argument("--body", required=True, help="PR body")
    parser.add_argument(
        "--labels",
        required=True,
        help="Comma-separated labels (empty string to clear labels)",
    )
    args = parser.parse_args(list(argv))
    labels = parse_labels(args.labels)

    try:
        number = find_pr_number(args.repo, args.head)
        if number is None:
            cmd = [
                "gh",
                "pr",
                "create",
                "--repo",
                args.repo,
                "--base",
                args.base,
                "--head",
                args.head,
                "--title",
                args.title,
                "--body",
                args.body,
            ]
            if labels:
                cmd.extend(["--label", ",".join(labels)])
            output = run(cmd).strip()
            if not output:
                number = find_pr_number(args.repo, args.head)
            else:
                number = int(output.split("/")[-1]) if output.rsplit("/", 1)[-1].isdigit() else None
            if number is None:
                number = find_pr_number(args.repo, args.head)
            if number is None:
                raise RuntimeError("Unable to determine created PR number")
        else:
            run(
                [
                    "gh",
                    "pr",
                    "edit",
                    str(number),
                    "--repo",
                    args.repo,
                    "--title",
                    args.title,
                    "--body",
                    args.body,
                ]
            )
        edit_labels(args.repo, number, labels)
        payload = read_pr(args.repo, number)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
