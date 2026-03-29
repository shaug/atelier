#!/usr/bin/env python3
"""Run bounded iterative refinement rounds for an implementation plan.

Provenance:
- Adapted from trycycle planning loop mechanics:
  - `orchestrator/run_phase.py`
  - `subagents/prompt-planning-initial.md`
  - `subagents/prompt-planning-edit.md`
- Baseline import reference: trycycle base commit `8ea3981`.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Literal

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


def _default_round_executor(_round_number: int, _plan_text: str) -> RoundResult:
    raise RuntimeError("round execution backend not configured")


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
    parser.add_argument("--initial-plan-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int, default=REFINEMENT_MAX_ROUNDS_DEFAULT)
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

    if args.simulate_verdicts:
        verdicts = [item.strip() for item in args.simulate_verdicts.split(",") if item.strip()]
        round_executor = _simulate_round_executor(verdicts)
    else:
        round_executor = _default_round_executor

    result = run_refinement(
        initial_plan_path=args.initial_plan_path.resolve(),
        output_dir=output_dir,
        round_executor=round_executor,
        max_rounds=args.max_rounds,
    )

    print(json.dumps({"status": result.status, "latest_verdict": result.latest_verdict}))
    return 0 if result.status == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
