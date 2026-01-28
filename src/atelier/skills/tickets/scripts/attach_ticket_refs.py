#!/usr/bin/env python3
"""Attach ticket references to a workspace config.user.json file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def normalize_refs(values: list[str] | None) -> list[str]:
    """Normalize ticket references, splitting comma-delimited inputs."""
    if not values:
        return []
    refs: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        for part in str(raw).split(","):
            ref = part.strip()
            if not ref:
                continue
            normalized = ref.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            refs.append(ref)
    return refs


def merge_refs(existing: list[str], new: list[str]) -> list[str]:
    """Merge ticket references, preserving order and deduping by case."""
    merged: list[str] = []
    seen: set[str] = set()
    for ref in [*existing, *new]:
        normalized = ref.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(ref)
    return merged


def load_config(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"config.user.json not found at {path}\n")
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"config.user.json is not valid JSON: {exc}\n")
        raise SystemExit(1)
    if not isinstance(data, dict):
        sys.stderr.write("config.user.json must contain a JSON object\n")
        raise SystemExit(1)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains config.user.json",
    )
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        help="Ticket reference (repeatable or comma-separated)",
    )
    args = parser.parse_args()

    refs = normalize_refs(args.ref)
    if not refs:
        sys.stderr.write("at least one --ref value is required\n")
        raise SystemExit(2)

    workspace_dir = Path(args.workspace)
    config_path = workspace_dir / "config.user.json"
    payload = load_config(config_path)

    tickets_section = payload.get("tickets")
    if tickets_section is None:
        tickets_section = {}
        payload["tickets"] = tickets_section
    if not isinstance(tickets_section, dict):
        sys.stderr.write("tickets section must be a JSON object\n")
        raise SystemExit(1)

    existing = tickets_section.get("refs")
    if existing is None:
        existing_refs: list[str] = []
    elif isinstance(existing, list):
        existing_refs = [str(item) for item in existing if item is not None]
    else:
        sys.stderr.write("tickets.refs must be a list\n")
        raise SystemExit(1)

    merged = merge_refs(existing_refs, refs)
    tickets_section["refs"] = merged

    with config_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    print(
        json.dumps(
            {"config": str(config_path), "refs": merged, "added": refs},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
