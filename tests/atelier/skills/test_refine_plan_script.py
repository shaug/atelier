from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TRYCYCLE_FIXTURE_ROOT = _REPO_ROOT / "tests" / "atelier" / "fixtures" / "trycycle_refinement"


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "refine-plan"
        / "scripts"
        / "run_refinement.py"
    )
    spec = importlib.util.spec_from_file_location("refine_plan_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_anchor_fixture() -> dict[str, list[str]]:
    fixture_path = _TRYCYCLE_FIXTURE_ROOT / "reference_anchors.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_refine_plan_verdict_parser_accepts_only_canonical_tokens() -> None:
    module = _load_script_module()

    assert module.parse_verdict("ready") == "READY"
    assert module.parse_verdict("revised") == "REVISED"
    assert module.parse_verdict("USER_DECISION_REQUIRED") == "USER_DECISION_REQUIRED"
    with pytest.raises(ValueError, match="unknown refinement verdict"):
        module.parse_verdict("NOT_READY")


def test_refine_plan_loop_defaults_to_max_rounds_five(tmp_path: Path) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    initial_plan_path.write_text("initial\n", encoding="utf-8")

    def fake_round_executor(round_number: int, plan_text: str):
        del round_number
        return module.RoundResult(verdict="READY", plan_text=plan_text + "done\n")

    result = module.run_refinement(
        initial_plan_path=initial_plan_path,
        output_dir=tmp_path / "artifacts",
        round_executor=fake_round_executor,
    )

    assert result.max_rounds == 5
    assert result.rounds_used == 1
    assert result.latest_verdict == "READY"


def test_refine_plan_emits_round_artifacts_per_iteration(tmp_path: Path) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    initial_plan_path.write_text("initial\n", encoding="utf-8")

    verdicts = iter(("REVISED", "READY"))

    def fake_round_executor(round_number: int, plan_text: str):
        verdict = next(verdicts)
        return module.RoundResult(
            verdict=verdict,
            plan_text=f"{plan_text}round-{round_number}\n",
            summary=f"summary-{round_number}",
        )

    output_dir = tmp_path / "artifacts"
    result = module.run_refinement(
        initial_plan_path=initial_plan_path,
        output_dir=output_dir,
        round_executor=fake_round_executor,
    )

    assert result.rounds_used == 2
    round_one = json.loads((output_dir / "rounds" / "round-01.json").read_text(encoding="utf-8"))
    round_two = json.loads((output_dir / "rounds" / "round-02.json").read_text(encoding="utf-8"))
    assert round_one["verdict"] == "REVISED"
    assert round_two["verdict"] == "READY"


def test_refine_plan_fails_closed_on_non_convergence(tmp_path: Path) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    initial_plan_path.write_text("initial\n", encoding="utf-8")

    def fake_round_executor(round_number: int, plan_text: str):
        return module.RoundResult(
            verdict="REVISED",
            plan_text=f"{plan_text}round-{round_number}\n",
        )

    result = module.run_refinement(
        initial_plan_path=initial_plan_path,
        output_dir=tmp_path / "artifacts",
        round_executor=fake_round_executor,
        max_rounds=3,
    )

    assert result.status == "non_converged"
    assert result.latest_verdict == "REVISED"
    assert result.rounds_used == 3


def test_refine_plan_main_without_simulation_is_runnable_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    appended_notes: list[tuple[str, ...]] = []
    initial_plan_path.write_text("initial\n", encoding="utf-8")

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(
                id=issue_id,
                notes=(
                    "planning_refinement.v1\n"
                    "authoritative: true\n"
                    "mode: requested\n"
                    "required: true\n"
                    "approval_status: approved\n"
                    "approval_source: operator\n"
                    "approved_by: planner-user\n"
                    "approved_at: 2026-03-29T12:00:00Z\n"
                    "plan_edit_rounds_max: 5\n"
                    "post_impl_review_rounds_max: 8\n"
                    "latest_verdict: REVISED\n"
                ),
            )

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            appended_notes.append(request.notes)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-123",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = module.main()

    assert exit_code == 1
    assert appended_notes
    payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "non_converged"
    assert payload["latest_verdict"] == "USER_DECISION_REQUIRED"


def test_refine_plan_main_without_simulation_without_runner_fails_closed_even_for_executable_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    appended_notes: list[tuple[str, ...]] = []
    initial_plan_path.write_text("- [ ] Step 1\n- [ ] Step 2\n", encoding="utf-8")

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(
                id=issue_id,
                notes=(
                    "planning_refinement.v1\n"
                    "authoritative: true\n"
                    "mode: requested\n"
                    "required: true\n"
                    "approval_status: approved\n"
                    "approval_source: operator\n"
                    "approved_by: planner-user\n"
                    "approved_at: 2026-03-29T12:00:00Z\n"
                    "plan_edit_rounds_max: 5\n"
                    "post_impl_review_rounds_max: 8\n"
                    "latest_verdict: REVISED\n"
                ),
            )

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            appended_notes.append(request.notes)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-123",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = module.main()

    assert exit_code == 1
    assert appended_notes
    payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "non_converged"
    assert payload["latest_verdict"] == "USER_DECISION_REQUIRED"


def test_refine_plan_main_persists_authoritative_refinement_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    appended_notes: list[tuple[str, ...]] = []
    initial_plan_path.write_text("initial\n", encoding="utf-8")

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(
                id=issue_id,
                notes=(
                    "planning_refinement.v1\n"
                    "authoritative: true\n"
                    "mode: requested\n"
                    "required: true\n"
                    "lineage_root: at-epic\n"
                    "approval_status: approved\n"
                    "approval_source: operator\n"
                    "approved_by: planner-user\n"
                    "approved_at: 2026-03-29T12:00:00Z\n"
                    "plan_edit_rounds_max: 7\n"
                    "post_impl_review_rounds_max: 9\n"
                    "latest_verdict: REVISED\n"
                ),
            )

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            appended_notes.append(request.notes)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-epic",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
            "--simulate-verdicts",
            "READY",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    assert appended_notes
    note = appended_notes[0][0]
    assert note.startswith("planning_refinement.v1")
    assert "authoritative: true" in note
    assert "required: true" in note
    assert "approval_status: approved" in note
    assert "latest_verdict: READY" in note
    assert "plan_edit_rounds_used: 1" in note
    assert f"initial_plan_path: {initial_plan_path.resolve()}" in note
    assert f"latest_plan_path: {(output_dir / 'latest-plan.md').resolve()}" in note
    assert f"round_log_dir: {(output_dir / 'rounds').resolve()}" in note


def test_refine_plan_loop_artifacts_match_trycycle_snapshot_anchors() -> None:
    anchors = _load_anchor_fixture()["mechanics_anchors"]
    loop_snapshot = (_TRYCYCLE_FIXTURE_ROOT / "trycycle-planning-loop.snapshot.md").read_text(
        encoding="utf-8"
    )
    live_material = "\n".join(
        (
            (
                _REPO_ROOT
                / "src"
                / "atelier"
                / "skills"
                / "refine-plan"
                / "subagents"
                / "prompt-planning-initial.md"
            ).read_text(encoding="utf-8"),
            (
                _REPO_ROOT
                / "src"
                / "atelier"
                / "skills"
                / "refine-plan"
                / "subagents"
                / "prompt-planning-edit.md"
            ).read_text(encoding="utf-8"),
            (
                _REPO_ROOT
                / "src"
                / "atelier"
                / "skills"
                / "refine-plan"
                / "scripts"
                / "run_refinement.py"
            ).read_text(encoding="utf-8"),
            (
                _REPO_ROOT
                / "src"
                / "atelier"
                / "skills"
                / "refine-plan"
                / "scripts"
                / "prompt_builder"
                / "build.py"
            ).read_text(encoding="utf-8"),
        )
    )
    missing_in_snapshot = [anchor for anchor in anchors if anchor not in loop_snapshot]
    missing_in_live = [anchor for anchor in anchors if anchor not in live_material]

    assert not missing_in_snapshot, f"snapshot anchors missing: {missing_in_snapshot}"
    assert not missing_in_live, f"live refine-plan anchors missing: {missing_in_live}"


def test_refine_plan_non_simulated_mode_uses_runtime_executor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    initial_plan_path.write_text("- [ ] Step 1\n", encoding="utf-8")
    calls: list[tuple[int, str]] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, notes="")

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            return SimpleNamespace(id=request.issue_id)

    def fake_runtime_executor(*, max_rounds: int):
        assert max_rounds == 5

        def executor(round_number: int, plan_text: str):
            calls.append((round_number, plan_text))
            return module.RoundResult(verdict="READY", plan_text=plan_text, summary="runtime")

        return executor

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(module, "_build_runtime_round_executor", fake_runtime_executor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-123",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    assert calls == [(1, "- [ ] Step 1\n")]


def test_refine_plan_non_simulated_uses_existing_refinement_round_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    initial_plan_path.write_text("- [ ] Step 1\n", encoding="utf-8")
    captured_max_rounds: list[int] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(
                id=issue_id,
                notes=(
                    "planning_refinement.v1\n"
                    "authoritative: true\n"
                    "mode: requested\n"
                    "required: true\n"
                    "approval_status: approved\n"
                    "approval_source: operator\n"
                    "approved_by: planner-user\n"
                    "approved_at: 2026-03-29T12:00:00Z\n"
                    "plan_edit_rounds_max: 9\n"
                    "latest_verdict: REVISED\n"
                ),
            )

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            return SimpleNamespace(id=request.issue_id)

    def fake_runtime_executor(*, max_rounds: int):
        captured_max_rounds.append(max_rounds)

        def executor(round_number: int, plan_text: str):
            del round_number
            return module.RoundResult(verdict="READY", plan_text=plan_text, summary="runtime")

        return executor

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(module, "_build_runtime_round_executor", fake_runtime_executor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-123",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    assert captured_max_rounds == [9]


def test_refine_plan_non_simulated_uses_policy_round_budget_when_no_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    initial_plan_path = tmp_path / "initial.md"
    output_dir = tmp_path / "artifacts"
    initial_plan_path.write_text("- [ ] Step 1\n", encoding="utf-8")
    captured_max_rounds: list[int] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, notes="")

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            return SimpleNamespace(id=request.issue_id)

    def fake_runtime_executor(*, max_rounds: int):
        captured_max_rounds.append(max_rounds)

        def executor(round_number: int, plan_text: str):
            del round_number
            return module.RoundResult(verdict="READY", plan_text=plan_text, summary="runtime")

        return executor

    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (tmp_path, tmp_path, None))
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(module, "_build_runtime_round_executor", fake_runtime_executor)
    monkeypatch.setattr(module, "_resolve_policy_round_limit", lambda **_kwargs: 11)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refinement.py",
            "--issue-id",
            "at-123",
            "--initial-plan-path",
            str(initial_plan_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    assert captured_max_rounds == [11]


def test_runtime_round_executor_renders_prompt_and_parses_runner_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    prompt_builder_calls: list[dict[str, object]] = []
    executed_commands: list[list[str]] = []

    def fake_run_prompt_builder(*, template_path: Path, bindings: dict[str, str]) -> str:
        prompt_builder_calls.append({"template_path": template_path, "bindings": bindings})
        return "rendered prompt"

    def fake_run(
        args: list[str],
        *,
        input: str,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del text, capture_output, check
        executed_commands.append(args)
        assert input == "rendered prompt"
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="## Plan verdict\nREADY\n\n# Updated plan\n- [ ] Step\n",
            stderr="",
        )

    monkeypatch.setattr(module, "_run_prompt_builder", fake_run_prompt_builder)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("ATELIER_REFINEMENT_ROUND_RUNNER", "echo-runner --round")

    executor = module._build_runtime_round_executor(max_rounds=5)
    result = executor(1, "- [ ] Step\n")

    assert result.verdict == "READY"
    assert result.plan_text == "# Updated plan\n- [ ] Step\n"
    assert prompt_builder_calls
    assert executed_commands == [["echo-runner", "--round"]]
