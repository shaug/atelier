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
import os
import re
import shlex
import subprocess
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
_ROUND_RUNNER_ENV: Final[str] = "ATELIER_REFINEMENT_ROUND_RUNNER"
_VERDICT_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^\s*##\s*Plan verdict\s*$", re.IGNORECASE)


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
    return RoundResult(
        verdict="USER_DECISION_REQUIRED",
        plan_text=plan_text,
        summary=(
            "no runtime round executor configured; "
            f"stopped at round {round_number} with fail-closed verdict"
        ),
    )


def _run_prompt_builder(*, template_path: Path, bindings: dict[str, str]) -> str:
    builder_root = Path(__file__).resolve().parent / "prompt_builder"
    if str(builder_root) not in sys.path:
        sys.path.insert(0, str(builder_root))

    from template_ast import (  # pyright: ignore[reportMissingImports]
        parse_template_text,
        render_nodes,
    )
    from validate_rendered import validate_rendered_prompt  # pyright: ignore[reportMissingImports]

    template_text = template_path.read_text(encoding="utf-8")
    full_template = (
        f"{template_text}\n\n"
        "<round-context>\n"
        "round: {ROUND_NUMBER}\n"
        "max_rounds: {MAX_ROUNDS}\n"
        "</round-context>\n\n"
        "<current-plan>\n"
        "{PLAN_TEXT}\n"
        "</current-plan>\n"
    )
    nodes = parse_template_text(full_template)
    prompt_text = render_nodes(nodes, bindings)
    validate_rendered_prompt(prompt_text)
    return prompt_text


def _runner_command_tokens() -> list[str] | None:
    raw = _clean(os.environ.get(_ROUND_RUNNER_ENV, ""))
    if raw is None:
        return None
    tokens = shlex.split(raw)
    if not tokens:
        return None
    return tokens


def _extract_verdict_and_plan(
    *, raw_output: str, fallback_plan: str
) -> tuple[RefinementVerdict, str]:
    lines = raw_output.splitlines()
    verdict_line_index: int | None = None
    for index, line in enumerate(lines):
        if _VERDICT_HEADER_RE.match(line):
            verdict_line_index = index
            break
    if verdict_line_index is None:
        raise ValueError("round output is missing '## Plan verdict' section")

    token_index = verdict_line_index + 1
    while token_index < len(lines) and not lines[token_index].strip():
        token_index += 1
    if token_index >= len(lines):
        raise ValueError("round output is missing verdict token")

    verdict_token = lines[token_index].strip().split()[0]
    verdict = parse_verdict(verdict_token)
    plan_tail = "\n".join(lines[token_index + 1 :]).strip()
    if not plan_tail:
        return verdict, fallback_plan
    return verdict, plan_tail + "\n"


def _run_round_runner(*, command: list[str], prompt_text: str) -> str:
    completed = subprocess.run(
        command,
        input=prompt_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip() or "no output"
        raise RuntimeError(f"round runner failed (exit {completed.returncode}): {detail}")
    return completed.stdout or ""


def _build_runtime_round_executor(*, max_rounds: int) -> RoundExecutor:
    runner_command = _runner_command_tokens()
    skill_root = Path(__file__).resolve().parent.parent
    initial_template = skill_root / "subagents" / "prompt-planning-initial.md"
    edit_template = skill_root / "subagents" / "prompt-planning-edit.md"

    def executor(round_number: int, plan_text: str) -> RoundResult:
        template_path = initial_template if round_number == 1 else edit_template
        try:
            prompt_text = _run_prompt_builder(
                template_path=template_path,
                bindings={
                    "PLAN_TEXT": plan_text,
                    "ROUND_NUMBER": str(round_number),
                    "MAX_ROUNDS": str(max_rounds),
                },
            )
        except Exception as exc:
            return RoundResult(
                verdict="USER_DECISION_REQUIRED",
                plan_text=plan_text,
                summary=f"prompt render failed at round {round_number}: {exc}",
            )

        if runner_command is None:
            fallback = _default_round_executor(round_number, plan_text)
            summary = fallback.summary or "runtime round runner not configured"
            return RoundResult(
                verdict=fallback.verdict,
                plan_text=fallback.plan_text,
                summary=f"runtime orchestration fallback: {summary}",
            )

        try:
            raw_output = _run_round_runner(command=runner_command, prompt_text=prompt_text)
            verdict, revised_plan = _extract_verdict_and_plan(
                raw_output=raw_output,
                fallback_plan=plan_text,
            )
            return RoundResult(
                verdict=verdict,
                plan_text=revised_plan,
                summary=f"runtime round {round_number} via {' '.join(runner_command)}",
            )
        except Exception as exc:
            return RoundResult(
                verdict="USER_DECISION_REQUIRED",
                plan_text=plan_text,
                summary=f"round execution failed at round {round_number}: {exc}",
            )

    return executor


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


def _notes_from_issue_model(issue: object) -> tuple[bool, str | None]:
    sentinel = object()
    raw_notes = getattr(issue, "notes", sentinel)
    if raw_notes is sentinel:
        return False, None
    return True, _normalize_notes_text(raw_notes)


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


def _load_existing_notes(*, store, issue_id: str, beads_root: Path, repo_root: Path) -> str | None:
    issue = asyncio.run(_resolve_work_item(store, issue_id))
    notes_present, notes_text = _notes_from_issue_model(issue)
    if notes_present:
        return notes_text

    from atelier.lib.beads import ShowIssueRequest, SubprocessBeadsClient

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    shown_issue = asyncio.run(client.show(ShowIssueRequest(issue_id=issue_id)))
    _present, shown_notes = _notes_from_issue_model(shown_issue)
    return shown_notes


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
    beads_root: Path,
    repo_root: Path,
    effective_plan_edit_rounds_max: int,
    effective_post_impl_review_rounds_max: int,
    result: RefinementRunResult,
    initial_plan_path: Path,
    output_dir: Path,
) -> None:
    from atelier.planning_refinement import (
        PlanningRefinementRecord,
        parse_refinement_blocks,
        select_winning_refinement,
    )
    from atelier.store import AppendNotesRequest

    existing_notes = _load_existing_notes(
        store=store,
        issue_id=issue_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
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
        plan_edit_rounds_max=effective_plan_edit_rounds_max,
        post_impl_review_rounds_max=effective_post_impl_review_rounds_max,
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


def _selected_refinement_round_limit(
    *, store, issue_id: str, beads_root: Path, repo_root: Path
) -> int | None:
    selected_plan_limit, _selected_post_limit = _selected_refinement_round_limits(
        store=store,
        issue_id=issue_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    return selected_plan_limit


def _selected_refinement_round_limits(
    *, store, issue_id: str, beads_root: Path, repo_root: Path
) -> tuple[int | None, int | None]:
    from atelier.planning_refinement import parse_refinement_blocks, select_winning_refinement

    notes = _load_existing_notes(
        store=store,
        issue_id=issue_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    selected = select_winning_refinement(parse_refinement_blocks(notes))
    if selected is None:
        return None, None
    return int(selected.plan_edit_rounds_max), int(selected.post_impl_review_rounds_max)


def _resolve_policy_round_limit(*, repo_root: Path) -> int | None:
    plan_limit, _post_limit = _resolve_policy_round_limits(repo_root=repo_root)
    return plan_limit


def _resolve_policy_post_impl_round_limit(*, repo_root: Path) -> int | None:
    _plan_limit, post_limit = _resolve_policy_round_limits(repo_root=repo_root)
    return post_limit


def _resolve_policy_round_limits(*, repo_root: Path) -> tuple[int | None, int | None]:
    from atelier import config as atelier_config
    from atelier import git, paths
    from atelier.commands.resolve import resolve_project_for_enlistment

    try:
        _repo_root, enlistment_path, _origin_raw, origin = git.resolve_repo_enlistment(repo_root)
        project_root, _project_config, _resolved_enlistment = resolve_project_for_enlistment(
            enlistment_path, origin
        )
        config_path = paths.project_config_path(project_root)
        project_config = atelier_config.load_project_config(config_path)
    except (Exception, SystemExit):
        return None, None
    if project_config is None:
        return None, None
    policy = atelier_config.resolve_refinement_policy(project_config)
    if policy is None:
        return None, None
    return int(policy.plan_edit_rounds_max), int(policy.post_impl_review_rounds_max)


def _resolve_effective_round_limits(
    *,
    cli_max_rounds: int | None,
    store,
    issue_id: str,
    beads_root: Path,
    repo_root: Path,
) -> tuple[int, int]:
    from atelier.planning_refinement import (
        DEFAULT_PLAN_EDIT_ROUNDS_MAX,
        DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
    )

    selected_plan_limit, selected_post_limit = _selected_refinement_round_limits(
        store=store,
        issue_id=issue_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    policy_plan_limit = _resolve_policy_round_limit(repo_root=repo_root)
    policy_post_limit = _resolve_policy_post_impl_round_limit(repo_root=repo_root)
    plan_limit = (
        int(cli_max_rounds)
        if cli_max_rounds is not None
        else selected_plan_limit
        if selected_plan_limit is not None
        else policy_plan_limit
        if policy_plan_limit is not None
        else DEFAULT_PLAN_EDIT_ROUNDS_MAX
    )
    post_limit = (
        selected_post_limit
        if selected_post_limit is not None
        else policy_post_limit
        if policy_post_limit is not None
        else DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX
    )
    return int(plan_limit), int(post_limit)


def _resolve_max_rounds(
    *,
    cli_max_rounds: int | None,
    store,
    issue_id: str,
    beads_root: Path,
    repo_root: Path,
) -> int:
    effective_plan_limit, _effective_post_limit = _resolve_effective_round_limits(
        cli_max_rounds=cli_max_rounds,
        store=store,
        issue_id=issue_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    return effective_plan_limit


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Epic or changeset issue id")
    parser.add_argument("--initial-plan-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int, default=None)
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
        issue_id = args.issue_id.strip()
        initial_plan_path = args.initial_plan_path.resolve()
        beads_root, repo_root, runtime_warning = _resolve_context(
            beads_dir=_clean(args.beads_dir),
            repo_dir=_clean(args.repo_dir),
        )
        if runtime_warning:
            print(runtime_warning, file=sys.stderr)
        store = _build_store(beads_root=beads_root, repo_root=repo_root)
        effective_plan_rounds_max, effective_post_impl_rounds_max = _resolve_effective_round_limits(
            cli_max_rounds=args.max_rounds,
            store=store,
            issue_id=issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        max_rounds = effective_plan_rounds_max

        if args.simulate_verdicts:
            verdicts = [item.strip() for item in args.simulate_verdicts.split(",") if item.strip()]
            round_executor = _simulate_round_executor(verdicts)
        else:
            round_executor = _build_runtime_round_executor(max_rounds=max_rounds)
        result = run_refinement(
            initial_plan_path=initial_plan_path,
            output_dir=output_dir,
            round_executor=round_executor,
            max_rounds=max_rounds,
        )
        _persist_refinement_evidence(
            store=store,
            issue_id=issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
            effective_plan_edit_rounds_max=effective_plan_rounds_max,
            effective_post_impl_review_rounds_max=effective_post_impl_rounds_max,
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
