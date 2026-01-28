#!/usr/bin/env python3
"""Resolve publish decisions from workspace config."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Missing workspace config: {path}", 2)
    except json.JSONDecodeError as exc:
        die(f"Invalid JSON in {path}: {exc}", 2)


def resolve_plan(workspace: dict, operation: str) -> dict:
    branch = workspace.get("branch")
    branch_pr = workspace.get("branch_pr")
    branch_history = workspace.get("branch_history")
    base = workspace.get("base")
    default_branch = None
    if isinstance(base, dict):
        default_branch = base.get("default_branch")

    if branch_pr is None or branch_history is None:
        die("Workspace config missing branch_pr or branch_history", 2)

    plan = {
        "operation": operation,
        "branch": branch,
        "branch_pr": branch_pr,
        "branch_history": branch_history,
        "default_branch": default_branch,
    }

    if branch_pr:
        plan.update(
            {
                "mode": "pr",
                "push_workspace_branch": True,
                "requires_pr": operation in {"publish", "finalize"},
                "integrate_default_branch": operation == "finalize",
            }
        )
    else:
        plan.update(
            {
                "mode": "direct",
                "push_workspace_branch": False,
                "requires_pr": False,
                "integrate_default_branch": True,
                "publish_equals_persist": True,
            }
        )

    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        default=".",
        help="Path to the workspace root containing config.sys.json",
    )
    parser.add_argument(
        "--operation",
        required=True,
        choices=("publish", "persist", "finalize"),
        help="Operation to resolve.",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace)
    config_path = workspace_root / "config.sys.json"
    config_payload = read_json(config_path)
    workspace = config_payload.get("workspace")
    if not isinstance(workspace, dict):
        die("Workspace config missing workspace section", 2)

    plan = resolve_plan(workspace, args.operation)
    print(json.dumps(plan, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
