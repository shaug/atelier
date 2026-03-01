#!/usr/bin/env python3
"""Check planner guardrails for epic-as-changeset and decomposition rules."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from atelier import beads
from atelier.bd_invocation import with_bd_mode

_LOC_TRIGGER = re.compile(r"\b(?:loc|estimate)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d{2,5}\b")
_APPROVAL = re.compile(r"\b(?:approve|approved|approval|sign[- ]?off|ok(?:ay)?)\b", re.IGNORECASE)
_RATIONALE = re.compile(
    r"\b(?:rationale|split because|split due to|reviewability|dependency|sequencing)\b",
    re.IGNORECASE,
)
_CROSS_CUTTING_INVARIANT = re.compile(
    r"\b(?:lifecycle|contract|invariant|state machine)\b",
    re.IGNORECASE,
)
_IMPACT_MAP = re.compile(r"\b(?:invariant impact map|impact map)\b", re.IGNORECASE)
_MUTATION_ENTRY_POINTS = re.compile(
    r"\b(?:mutation entry points?|write entry points?)\b",
    re.IGNORECASE,
)
_RECOVERY_PATHS = re.compile(
    r"\b(?:recovery paths?|rollback paths?|failure recovery)\b",
    re.IGNORECASE,
)
_EXTERNAL_SIDE_EFFECT_ADAPTERS = re.compile(
    r"\b(?:external side[- ]effect adapters?|provider adapters?|external adapters?)\b",
    re.IGNORECASE,
)
_CONCERN_DOMAINS: dict[str, re.Pattern[str]] = {
    "lifecycle-state-machine": re.compile(
        r"\b(?:lifecycle|state machine|state transition)\b",
        re.IGNORECASE,
    ),
    "external-ticket-provider-sync": re.compile(
        r"\b(?:external provider(?: sync)?|external ticket sync|ticket sync|"
        r"provider sync|sync adapters?)\b",
        re.IGNORECASE,
    ),
    "dry-run-observability": re.compile(
        r"\b(?:dry[- ]?run|observability|telemetry|metrics|instrumentation)\b",
        re.IGNORECASE,
    ),
}
_RESPLIT_THRESHOLD_TRIGGER = re.compile(
    r"\b(?:re[- ]?split trigger|split trigger|loc threshold|file threshold)\b",
    re.IGNORECASE,
)
_RESPLIT_THRESHOLD_NUMERIC = re.compile(r">\s*(?:400|800)\b")
_RESPLIT_NEW_DOMAIN_TRIGGER = re.compile(
    r"\b(?:new concern domain|additional concern domain|new domain during review)\b",
    re.IGNORECASE,
)
_DEFERRED_FOLLOW_ON_ACTION = re.compile(
    r"\b(?:deferred follow[- ]on|create deferred changeset|stack extension|extend stack)\b",
    re.IGNORECASE,
)
_REVIEW_SCOPE_GROWTH = re.compile(
    r"\b(?:review feedback|scope expansion during review|scope grows during review)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _GuardrailReport:
    path_summary: str | None
    violations: list[str]
    checked_ids: list[str]


def _run_bd_json(args: list[str], *, beads_dir: str | None) -> list[dict[str, object]]:
    env = dict(os.environ)
    command = with_bd_mode(*args, beads_dir=beads_dir, env=env)
    if beads_dir:
        env["BEADS_DIR"] = beads_dir
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        print("error: missing required command: bd", file=sys.stderr)
        raise SystemExit(1)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"error: bd command failed ({' '.join(command)}): {detail}", file=sys.stderr)
        raise SystemExit(1)
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    payload = json.loads(raw)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _issue_id(issue: dict[str, object]) -> str:
    return str(issue.get("id") or "").strip()


def _labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _normalize_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item is not None)
    return ""


def _text_blob(issue: dict[str, object]) -> str:
    fields = (
        "title",
        "description",
        "notes",
        "acceptance",
        "acceptance_criteria",
        "design",
    )
    return "\n".join(
        part for part in (_normalize_text(issue.get(field)) for field in fields) if part.strip()
    )


def _extract_loc_estimate(text: str) -> int | None:
    values: list[int] = []
    for line in text.splitlines():
        if not _LOC_TRIGGER.search(line):
            continue
        numbers = [int(value) for value in _NUMBER.findall(line)]
        if numbers:
            values.append(max(numbers))
    if not values:
        return None
    return max(values)


def _cross_cutting_corpus(
    *,
    epic_issue: dict[str, object] | None,
    target_changesets: list[dict[str, object]],
) -> str:
    parts: list[str] = []
    if epic_issue is not None:
        parts.append(_text_blob(epic_issue))
    parts.extend(_text_blob(issue) for issue in target_changesets)
    return "\n".join(part for part in parts if part.strip())


def _subject_id(
    *,
    epic_issue: dict[str, object] | None,
    target_changesets: list[dict[str, object]],
) -> str:
    if epic_issue is not None:
        epic_id = _issue_id(epic_issue)
        if epic_id:
            return epic_id
    if target_changesets:
        target_id = _issue_id(target_changesets[0])
        if target_id:
            return target_id
    return "(changeset)"


def _matched_concern_domains(text: str) -> list[str]:
    matched: list[str] = []
    for domain, pattern in _CONCERN_DOMAINS.items():
        if pattern.search(text):
            matched.append(domain)
    return matched


def _has_resplit_threshold_trigger(text: str) -> bool:
    return bool(_RESPLIT_THRESHOLD_TRIGGER.search(text) or _RESPLIT_THRESHOLD_NUMERIC.search(text))


def _load_issue(issue_id: str, *, beads_dir: str | None) -> dict[str, object] | None:
    issues = _run_bd_json(["show", issue_id, "--json"], beads_dir=beads_dir)
    if not issues:
        return None
    return issues[0]


def _list_child_changesets(epic_id: str, *, beads_dir: str | None) -> list[dict[str, object]]:
    beads_root = Path(beads_dir).resolve() if beads_dir else Path.cwd() / ".beads"
    cwd = Path.cwd()
    return beads.list_child_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=cwd,
        include_closed=True,
    )


def _evaluate_guardrails(
    *,
    epic_issue: dict[str, object] | None,
    child_changesets: list[dict[str, object]],
    target_changesets: list[dict[str, object]],
) -> _GuardrailReport:
    violations: list[str] = []
    path_summary: str | None = None

    for issue in target_changesets:
        issue_id = _issue_id(issue) or "(unknown)"
        text = _text_blob(issue)
        estimate = _extract_loc_estimate(text)
        if estimate is None:
            violations.append(f"{issue_id}: missing LOC estimate in notes/description.")
            continue
        if estimate > 800 and not _APPROVAL.search(text):
            violations.append(
                f"{issue_id}: LOC estimate {estimate} exceeds 800 without explicit approval note."
            )

    if epic_issue is not None:
        epic_id = _issue_id(epic_issue) or "(epic)"
        if not child_changesets:
            path_summary = (
                f"{epic_id}: compliant single-unit path (epic is the executable changeset)."
            )
        elif len(child_changesets) == 1:
            child = child_changesets[0]
            child_id = _issue_id(child) or "(child)"
            rationale_text = "\n".join((_text_blob(epic_issue), _text_blob(child)))
            if _RATIONALE.search(rationale_text):
                path_summary = (
                    f"{epic_id}: one child changeset ({child_id}) with explicit rationale."
                )
            else:
                path_summary = f"{epic_id}: one child changeset ({child_id}) without rationale."
                violations.append(
                    f"{epic_id}: one-child anti-pattern; add decomposition rationale "
                    f"for {child_id} or keep the epic as the executable changeset."
                )
        else:
            path_summary = (
                f"{epic_id}: multi-unit decomposition ({len(child_changesets)} children)."
            )

    corpus = _cross_cutting_corpus(epic_issue=epic_issue, target_changesets=target_changesets)
    if _CROSS_CUTTING_INVARIANT.search(corpus):
        subject = _subject_id(epic_issue=epic_issue, target_changesets=target_changesets)
        has_impact_map = _IMPACT_MAP.search(corpus)
        has_mutation_entry_points = _MUTATION_ENTRY_POINTS.search(corpus)
        has_recovery_paths = _RECOVERY_PATHS.search(corpus)
        has_external_adapters = _EXTERNAL_SIDE_EFFECT_ADAPTERS.search(corpus)
        if not (
            has_impact_map
            and has_mutation_entry_points
            and has_recovery_paths
            and has_external_adapters
        ):
            violations.append(
                f"{subject}: missing invariant impact map coverage for mutation entry points, "
                "recovery paths, and external side-effect adapters."
            )

        concern_domains = _matched_concern_domains(corpus)
        if epic_issue is not None and len(concern_domains) >= 2 and len(child_changesets) < 2:
            violations.append(
                f"{subject}: touches multiple concern domains ({', '.join(concern_domains)}) "
                "without stacked decomposition; split into multiple changesets or record "
                "explicit decomposition constraints."
            )

        has_threshold_trigger = _has_resplit_threshold_trigger(corpus)
        has_new_domain_trigger = _RESPLIT_NEW_DOMAIN_TRIGGER.search(corpus)
        if not (has_threshold_trigger and has_new_domain_trigger):
            violations.append(
                f"{subject}: missing explicit re-split triggers for threshold crossings and "
                "new concern domains discovered during review."
            )

        has_deferred_follow_on = _DEFERRED_FOLLOW_ON_ACTION.search(corpus)
        if not has_deferred_follow_on:
            violations.append(
                f"{subject}: missing required planner action when re-split triggers fire "
                "(create deferred follow-on work or stack extension)."
            )

        if not _REVIEW_SCOPE_GROWTH.search(corpus):
            violations.append(
                f"{subject}: missing review-feedback scope-growth guidance; capture expansion "
                "immediately as deferred follow-on work or stack extension."
            )

    checked_ids = [_issue_id(issue) for issue in target_changesets if _issue_id(issue)]
    return _GuardrailReport(
        path_summary=path_summary,
        violations=violations,
        checked_ids=checked_ids,
    )


def _render_report(report: _GuardrailReport) -> str:
    lines = ["Planner changeset guardrails report:"]
    if report.path_summary:
        lines.append(f"- Path: {report.path_summary}")
    lines.append(f"- Checked changesets: {len(report.checked_ids)}")
    if report.checked_ids:
        lines.append(f"- IDs: {', '.join(report.checked_ids)}")
    if report.violations:
        lines.append("- Violations:")
        for violation in report.violations:
            lines.append(f"  - {violation}")
    else:
        lines.append("- Violations: none")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epic-id", help="Epic id to validate")
    parser.add_argument(
        "--changeset-id",
        action="append",
        dest="changeset_ids",
        default=[],
        help="Changeset id to validate (repeatable)",
    )
    parser.add_argument(
        "--beads-dir",
        default=os.environ.get("BEADS_DIR", ""),
        help="Beads directory path (defaults to BEADS_DIR env var)",
    )
    args = parser.parse_args()

    epic_id = str(args.epic_id or "").strip()
    changeset_ids = [str(value).strip() for value in args.changeset_ids if str(value).strip()]
    beads_dir = str(args.beads_dir or "").strip() or None
    if beads_dir and not Path(beads_dir).exists():
        print(f"error: beads dir not found: {beads_dir}", file=sys.stderr)
        raise SystemExit(1)
    if not epic_id and not changeset_ids:
        parser.error("provide --epic-id or at least one --changeset-id")

    epic_issue = _load_issue(epic_id, beads_dir=beads_dir) if epic_id else None
    child_changesets = _list_child_changesets(epic_id, beads_dir=beads_dir) if epic_id else []

    target_changesets: list[dict[str, object]] = []
    if changeset_ids:
        for changeset_id in changeset_ids:
            issue = _load_issue(changeset_id, beads_dir=beads_dir)
            if issue is not None:
                target_changesets.append(issue)
    elif child_changesets:
        target_changesets = child_changesets
    elif epic_issue is not None and not child_changesets:
        target_changesets = [epic_issue]

    report = _evaluate_guardrails(
        epic_issue=epic_issue,
        child_changesets=child_changesets,
        target_changesets=target_changesets,
    )
    print(_render_report(report))


if __name__ == "__main__":
    main()
