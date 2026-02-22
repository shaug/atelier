#!/usr/bin/env python3
"""Repair collapsed dependency parent lineage metadata for active changesets."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from atelier import beads, changeset_fields, dependency_lineage, git


@dataclass(frozen=True)
class LineageRepairCandidate:
    """Potential lineage repair action for a single changeset."""

    epic_id: str
    changeset_id: str
    current_parent: str | None
    resolved_parent: str | None
    blocked: bool
    blocker_reason: str | None
    diagnostics: tuple[str, ...]

    @property
    def can_repair(self) -> bool:
        return not self.blocked and bool(self.resolved_parent)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect active epics for collapsed dependency lineage metadata and "
            "optionally repair `changeset.parent_branch`."
        )
    )
    parser.add_argument(
        "--beads-root",
        default=None,
        help="Path to the Beads store. Defaults to BEADS_DIR or .beads.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root used as bd cwd and git metadata source.",
    )
    parser.add_argument(
        "--epic",
        action="append",
        default=[],
        help="Epic id to inspect (repeat for multiple epics). Defaults to open epics.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe repairs to `changeset.parent_branch` for fixable rows.",
    )
    return parser.parse_args()


def _resolve_beads_root(raw_value: str | None) -> Path:
    if raw_value:
        return Path(raw_value).expanduser().resolve()
    env_value = os.environ.get("BEADS_DIR") or str(Path.cwd().joinpath(".beads"))
    return Path(env_value).resolve()


def _resolve_epics(
    *,
    beads_root: Path,
    repo_root: Path,
    explicit_epics: Iterable[str],
) -> list[dict[str, object]]:
    selected = [epic_id.strip() for epic_id in explicit_epics if epic_id.strip()]
    if selected:
        results: list[dict[str, object]] = []
        for epic_id in selected:
            rows = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
            if rows:
                results.append(rows[0])
        return results
    return beads.run_bd_json(
        ["list", "--label", "at:epic", "--status", "open"],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _evaluate_epic(
    *,
    epic_id: str,
    changesets: list[dict[str, object]],
) -> list[LineageRepairCandidate]:
    by_id = {
        issue_id: issue
        for issue in changesets
        if isinstance((issue_id := issue.get("id")), str) and issue_id
    }
    candidates: list[LineageRepairCandidate] = []
    for issue in changesets:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        root_branch = changeset_fields.root_branch(issue)
        parent_branch = changeset_fields.parent_branch(issue)
        lineage = dependency_lineage.resolve_parent_lineage(
            issue,
            root_branch=root_branch,
            lookup_issue=by_id.get,
        )
        if not lineage.has_dependency_lineage:
            continue
        if lineage.used_dependency_parent and lineage.effective_parent_branch != parent_branch:
            candidates.append(
                LineageRepairCandidate(
                    epic_id=epic_id,
                    changeset_id=issue_id,
                    current_parent=parent_branch,
                    resolved_parent=lineage.effective_parent_branch,
                    blocked=lineage.blocked,
                    blocker_reason=lineage.blocker_reason,
                    diagnostics=lineage.diagnostics,
                )
            )
            continue
        if lineage.blocked:
            candidates.append(
                LineageRepairCandidate(
                    epic_id=epic_id,
                    changeset_id=issue_id,
                    current_parent=parent_branch,
                    resolved_parent=None,
                    blocked=True,
                    blocker_reason=lineage.blocker_reason,
                    diagnostics=lineage.diagnostics,
                )
            )
    return candidates


def _apply_repair(
    *,
    candidate: LineageRepairCandidate,
    issue: dict[str, object],
    beads_root: Path,
    repo_root: Path,
) -> bool:
    resolved_parent = candidate.resolved_parent
    if not resolved_parent:
        return False
    root_branch = changeset_fields.root_branch(issue)
    work_branch = changeset_fields.work_branch(issue)
    parent_base = git.git_rev_parse(repo_root, resolved_parent)
    beads.update_changeset_branch_metadata(
        candidate.changeset_id,
        root_branch=root_branch,
        parent_branch=resolved_parent,
        work_branch=work_branch,
        root_base=None,
        parent_base=parent_base,
        beads_root=beads_root,
        cwd=repo_root,
        allow_override=True,
    )
    return True


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    beads_root = _resolve_beads_root(args.beads_root)
    epics = _resolve_epics(
        beads_root=beads_root,
        repo_root=repo_root,
        explicit_epics=args.epic,
    )
    if not epics:
        print("No epics found.")
        return 0

    repairs: list[LineageRepairCandidate] = []
    changeset_index: dict[str, dict[str, object]] = {}
    for epic in epics:
        epic_id = str(epic.get("id") or "").strip()
        if not epic_id:
            continue
        rows = beads.run_bd_json(
            ["list", "--parent", epic_id, "--label", "at:changeset", "--status", "open"],
            beads_root=beads_root,
            cwd=repo_root,
        )
        repairs.extend(_evaluate_epic(epic_id=epic_id, changesets=rows))
        for row in rows:
            issue_id = row.get("id")
            if isinstance(issue_id, str) and issue_id:
                changeset_index[issue_id] = row

    if not repairs:
        print("No collapsed dependency lineage found.")
        return 0

    print("Dependency lineage report:")
    for repair in repairs:
        prefix = "BLOCKED" if repair.blocked else "FIX"
        print(
            f"- [{prefix}] {repair.changeset_id}: "
            f"current_parent={repair.current_parent!r}, "
            f"resolved_parent={repair.resolved_parent!r}"
        )
        if repair.blocker_reason:
            print(f"  reason: {repair.blocker_reason}")
        for diagnostic in repair.diagnostics:
            print(f"  detail: {diagnostic}")

    if not args.apply:
        return 0

    applied = 0
    for repair in repairs:
        if not repair.can_repair:
            continue
        issue = changeset_index.get(repair.changeset_id)
        if issue is None:
            continue
        if _apply_repair(
            candidate=repair,
            issue=issue,
            beads_root=beads_root,
            repo_root=repo_root,
        ):
            applied += 1
    print(f"Applied {applied} lineage repair(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
