#!/usr/bin/env python3
"""Run bounded iterative refinement rounds for an implementation plan.

Provenance:
- Adapted from trycycle planning loop mechanics:
  - `orchestrator/run_phase.py`
  - `_prepare_phase`
  - `_command_run`
  - `subagents/prompt-planning-initial.md`
  - `subagents/prompt-planning-edit.md`
- Baseline import reference: trycycle base commit `8ea3981`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Literal

_SHARED_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "shared" / "scripts"
if str(_SHARED_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS_ROOT))

from projected_bootstrap import (  # pyright: ignore[reportMissingImports]
    bootstrap_projected_atelier_script,
)

bootstrap_projected_atelier_script(
    script_path=Path(__file__).resolve(),
    argv=sys.argv[1:],
    require_runtime_health=__name__ == "__main__",
)

REFINEMENT_MAX_ROUNDS_DEFAULT: Final[int] = 5
RefinementVerdict = Literal["READY", "REVISED", "USER_DECISION_REQUIRED"]


@dataclass(frozen=True)
class RoundResult:
    """One refinement round output.

    Attributes:
        verdict: Round verdict token.
        plan_text: Full revised plan text.
        summary: Optional short round summary.
    """

    verdict: str
    plan_text: str
    summary: str | None = None


@dataclass(frozen=True)
class RefinementRunResult:
    """Overall refinement loop outcome."""

    status: Literal["ready", "non_converged"]
    max_rounds: int
    rounds_used: int
    latest_verdict: RefinementVerdict
    output_dir: Path


RoundExecutor = Callable[[int, str], RoundResult]
_UNCHECKED_CHECKLIST_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*]\s+\[\s\]\s+\S")
_NUMBERED_STEP_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\d+\.\s+\S")


def parse_verdict(raw: str) -> RefinementVerdict:
    """Parse and validate a refinement verdict token.

    Args:
        raw: Raw verdict string.

    Returns:
        Canonical refinement verdict token.

    Raises:
        ValueError: If the token is not canonical.
    """
    normalized = raw.strip().upper()
    if normalized == "READY":
        return "READY"
    if normalized == "REVISED":
        return "REVISED"
    if normalized == "USER_DECISION_REQUIRED":
        return "USER_DECISION_REQUIRED"
    raise ValueError(f"unknown refinement verdict: {raw!r}")


def run_refinement(
    *,
    initial_plan_path: Path,
    output_dir: Path,
    round_executor: RoundExecutor,
    max_rounds: int = REFINEMENT_MAX_ROUNDS_DEFAULT,
) -> RefinementRunResult:
    """Execute bounded refinement rounds.

    Args:
        initial_plan_path: Path to initial plan markdown.
        output_dir: Artifact output directory.
        round_executor: Callable that returns one round result.
        max_rounds: Maximum refinement rounds.

    Returns:
        Refinement run result.
    """
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")

    plan_text = initial_plan_path.read_text(encoding="utf-8")
    rounds_dir = output_dir / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)

    latest_verdict: RefinementVerdict = "REVISED"
    rounds_used = 0
    for round_number in range(1, max_rounds + 1):
        round_result = round_executor(round_number, plan_text)
        verdict = parse_verdict(round_result.verdict)
        latest_verdict = verdict
        plan_text = round_result.plan_text
        rounds_used = round_number

        round_plan_path = rounds_dir / f"round-{round_number:02d}-plan.md"
        round_plan_path.write_text(plan_text, encoding="utf-8")
        round_json_path = rounds_dir / f"round-{round_number:02d}.json"
        round_json_path.write_text(
            json.dumps(
                {
                    "round": round_number,
                    "verdict": verdict,
                    "summary": round_result.summary,
                    "plan_path": str(round_plan_path),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        if verdict == "READY":
            (output_dir / "latest-plan.md").write_text(plan_text, encoding="utf-8")
            result = RefinementRunResult(
                status="ready",
                max_rounds=max_rounds,
                rounds_used=rounds_used,
                latest_verdict=verdict,
                output_dir=output_dir,
            )
            _write_result(output_dir=output_dir, result=result)
            return result

        if verdict == "USER_DECISION_REQUIRED":
            (output_dir / "latest-plan.md").write_text(plan_text, encoding="utf-8")
            result = RefinementRunResult(
                status="non_converged",
                max_rounds=max_rounds,
                rounds_used=rounds_used,
                latest_verdict=verdict,
                output_dir=output_dir,
            )
            _write_result(output_dir=output_dir, result=result)
            return result

    (output_dir / "latest-plan.md").write_text(plan_text, encoding="utf-8")
    result = RefinementRunResult(
        status="non_converged",
        max_rounds=max_rounds,
        rounds_used=rounds_used,
        latest_verdict=latest_verdict,
        output_dir=output_dir,
    )
    _write_result(output_dir=output_dir, result=result)
    return result


def _default_round_executor(round_number: int, plan_text: str) -> RoundResult:
    if _looks_executable_plan(plan_text):
        return RoundResult(
            verdict="READY",
            plan_text=plan_text,
            summary=(
                "default local executor marked plan ready from executable task structure "
                f"at round {round_number}"
            ),
        )
    return RoundResult(
        verdict="USER_DECISION_REQUIRED",
        plan_text=plan_text,
        summary=(
            "no runtime round executor configured; "
            f"stopped at round {round_number} with fail-closed verdict"
        ),
    )


def _looks_executable_plan(plan_text: str) -> bool:
    """Return whether plan text has deterministic executable-task structure."""
    for line in plan_text.splitlines():
        if _UNCHECKED_CHECKLIST_RE.match(line):
            return True
        if _NUMBERED_STEP_RE.match(line):
            return True
    return False


def _build_store(*, beads_root: Path, repo_root: Path):
    from atelier.lib.beads import SubprocessBeadsClient
    from atelier.store import build_atelier_store

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client)


def _resolve_context(
    *,
    beads_dir: str | None,
    repo_dir: str | None,
) -> tuple[Path, Path, str | None]:
    from atelier.beads_context import resolve_runtime_repo_dir_hint, resolve_skill_beads_context

    repo_hint, runtime_warning = resolve_runtime_repo_dir_hint(repo_dir=repo_dir)
    context = resolve_skill_beads_context(beads_dir=beads_dir, repo_dir=repo_hint)
    return context.beads_root, context.repo_root, runtime_warning or context.override_warning


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_notes_text(value: object) -> str | None:
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, (list, tuple)):
        joined = "\n".join(str(item).strip() for item in value if str(item).strip())
        return joined or None
    return None


async def _resolve_work_item(store, issue_id: str):
    try:
        return await store.get_epic(issue_id)
    except LookupError:
        pass
    try:
        return await store.get_changeset(issue_id)
    except LookupError as exc:
        raise RuntimeError(f"issue not found or not executable work: {issue_id}") from exc


def _required_hint_from_scope(blocks: tuple[object, ...]) -> bool:
    authoritative = tuple(block for block in blocks if getattr(block, "authoritative_hint", False))
    scope = authoritative or blocks
    return any(bool(getattr(block, "required_hint", False)) for block in scope)


def _render_refinement_note(record) -> str:
    payload = record.model_dump(exclude_none=True)
    ordered_keys = (
        "authoritative",
        "mode",
        "required",
        "lineage_root",
        "approval_status",
        "approval_source",
        "approved_by",
        "approved_at",
        "plan_edit_rounds_max",
        "post_impl_review_rounds_max",
        "plan_edit_rounds_used",
        "latest_verdict",
        "initial_plan_path",
        "latest_plan_path",
        "round_log_dir",
    )
    lines = ["planning_refinement.v1"]
    for key in ordered_keys:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _persist_refinement_evidence(
    *,
    store,
    issue_id: str,
    result: RefinementRunResult,
    initial_plan_path: Path,
    output_dir: Path,
) -> None:
    from atelier.planning_refinement import (
        DEFAULT_PLAN_EDIT_ROUNDS_MAX,
        DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
        PlanningRefinementRecord,
        parse_refinement_blocks,
        select_winning_refinement,
    )
    from atelier.store import AppendNotesRequest

    issue = asyncio.run(_resolve_work_item(store, issue_id))
    existing_notes = _normalize_notes_text(getattr(issue, "notes", None))
    blocks = parse_refinement_blocks(existing_notes)
    selected = select_winning_refinement(blocks)
    required_hint = _required_hint_from_scope(blocks)
    record = PlanningRefinementRecord(
        authoritative=True,
        mode=selected.mode if selected is not None else "requested",
        required=selected.required if selected is not None else required_hint,
        lineage_root=selected.lineage_root if selected is not None else None,
        approval_status=selected.approval_status if selected is not None else "missing",
        approval_source=selected.approval_source if selected is not None else None,
        approved_by=selected.approved_by if selected is not None else None,
        approved_at=selected.approved_at if selected is not None else None,
        plan_edit_rounds_max=(
            selected.plan_edit_rounds_max if selected is not None else DEFAULT_PLAN_EDIT_ROUNDS_MAX
        ),
        post_impl_review_rounds_max=(
            selected.post_impl_review_rounds_max
            if selected is not None
            else DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX
        ),
        plan_edit_rounds_used=result.rounds_used,
        latest_verdict=result.latest_verdict,
        initial_plan_path=str(initial_plan_path),
        latest_plan_path=str((output_dir / "latest-plan.md").resolve()),
        round_log_dir=str((output_dir / "rounds").resolve()),
    )
    note = _render_refinement_note(record)
    asyncio.run(store.append_notes(AppendNotesRequest(issue_id=issue_id, notes=(note,))))


def _write_result(*, output_dir: Path, result: RefinementRunResult) -> None:
    payload = {
        "status": result.status,
        "max_rounds": result.max_rounds,
        "rounds_used": result.rounds_used,
        "latest_verdict": result.latest_verdict,
        "output_dir": str(result.output_dir),
    }
    (output_dir / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _simulate_round_executor(verdicts: list[str]) -> RoundExecutor:
    if not verdicts:
        raise ValueError("simulate verdict sequence must include at least one token")
    normalized_verdicts = [parse_verdict(verdict) for verdict in verdicts]

    def executor(round_number: int, plan_text: str) -> RoundResult:
        verdict_index = min(round_number - 1, len(normalized_verdicts) - 1)
        verdict = normalized_verdicts[verdict_index]
        return RoundResult(
            verdict=verdict,
            plan_text=f"{plan_text}\n# refinement round {round_number}\n",
            summary=f"simulated round {round_number}",
        )

    return executor


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Epic or changeset issue id")
    parser.add_argument("--initial-plan-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int, default=REFINEMENT_MAX_ROUNDS_DEFAULT)
    parser.add_argument("--beads-dir", default="", help="Beads directory override")
    parser.add_argument("--repo-dir", default="", help="Repo root override")
    parser.add_argument(
        "--simulate-verdicts",
        default="",
        help="Comma-separated verdict sequence for local simulation",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.simulate_verdicts:
            verdicts = [item.strip() for item in args.simulate_verdicts.split(",") if item.strip()]
            round_executor = _simulate_round_executor(verdicts)
        else:
            round_executor = _default_round_executor

        initial_plan_path = args.initial_plan_path.resolve()
        result = run_refinement(
            initial_plan_path=initial_plan_path,
            output_dir=output_dir,
            round_executor=round_executor,
            max_rounds=args.max_rounds,
        )
        beads_root, repo_root, runtime_warning = _resolve_context(
            beads_dir=_clean(args.beads_dir),
            repo_dir=_clean(args.repo_dir),
        )
        if runtime_warning:
            print(runtime_warning, file=sys.stderr)
        store = _build_store(beads_root=beads_root, repo_root=repo_root)
        _persist_refinement_evidence(
            store=store,
            issue_id=args.issue_id.strip(),
            result=result,
            initial_plan_path=initial_plan_path,
            output_dir=output_dir,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"status": result.status, "latest_verdict": result.latest_verdict}))
    return 0 if result.status == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
