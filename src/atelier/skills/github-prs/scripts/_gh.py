#!/usr/bin/env python3
"""Shared GitHub CLI helpers for github-prs scripts."""

from __future__ import annotations

import json
import subprocess


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
        entry["number"]
        for entry in payload
        if isinstance(entry, dict) and isinstance(entry.get("number"), int)
    )
    return numbers[-1] if numbers else None


def split_repo_slug(repo: str) -> tuple[str, str]:
    owner, sep, name = repo.partition("/")
    if not owner or not name or sep != "/":
        raise RuntimeError("repo must be in owner/name format")
    return owner, name
