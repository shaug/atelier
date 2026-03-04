from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_doctor_help_shows_format_choices() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["doctor", "--help"], color=False, terminal_width=220)

    assert result.exit_code == 0
    assert "--format" in result.output
    assert "[table|json]" in result.output
    assert "--format        TEXT" not in result.output


def test_work_help_shows_mode_select_and_run_mode_choices() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["work", "--help"], color=False, terminal_width=220)

    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "[prompt|auto]" in result.output
    assert "--select" in result.output
    assert "first-eligible" in result.output
    assert "oldest-feedback" in result.output
    assert "--run-mode" in result.output
    assert "[once|default|watch]" in result.output


def test_global_help_shows_log_level_choices() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"], color=False, terminal_width=220)

    assert result.exit_code == 0
    assert "--log-level" in result.output
    assert "[trace|debug|info|" in result.output
    assert "--log-level                           TEXT" not in result.output


def test_choice_flags_accept_case_insensitive_and_underscore_aliases() -> None:
    doctor_capture: dict[str, object] = {}
    work_capture: dict[str, object] = {}

    def fake_doctor(args: SimpleNamespace) -> None:
        doctor_capture["format"] = args.format

    def fake_start_worker(args: SimpleNamespace) -> None:
        work_capture["mode"] = args.mode
        work_capture["select"] = args.select
        work_capture["run_mode"] = args.run_mode

    runner = CliRunner()
    with (
        patch("atelier.cli.doctor_cmd", fake_doctor),
        patch("atelier.commands.work.start_worker", fake_start_worker),
    ):
        doctor_result = runner.invoke(cli.app, ["doctor", "--format", "JSON"], color=False)
        work_result = runner.invoke(
            cli.app,
            [
                "work",
                "--mode",
                "AUTO",
                "--select",
                "oldest_feedback",
                "--run-mode",
                "ONCE",
            ],
            color=False,
        )

    assert doctor_result.exit_code == 0
    assert doctor_capture["format"] == "json"

    assert work_result.exit_code == 0
    assert work_capture == {
        "mode": "auto",
        "select": "oldest-feedback",
        "run_mode": "once",
    }


def test_init_policy_choice_flags_normalize_to_canonical_values() -> None:
    captured: dict[str, object] = {}

    def fake_init_project(args: object) -> None:
        captured["branch_pr_mode"] = getattr(args, "branch_pr_mode")
        captured["branch_history"] = getattr(args, "branch_history")
        captured["branch_squash_message"] = getattr(args, "branch_squash_message")
        captured["branch_pr_strategy"] = getattr(args, "branch_pr_strategy")

    runner = CliRunner()
    with patch("atelier.cli.init_cmd.init_project", fake_init_project):
        result = runner.invoke(
            cli.app,
            [
                "init",
                "--branch-pr-mode",
                "DRAFT",
                "--branch-history",
                "MERGE",
                "--branch-squash-message",
                "deterministic",
                "--branch-pr-strategy",
                "on_parent_approved",
                "--yes",
            ],
            color=False,
        )

    assert result.exit_code == 0
    assert captured == {
        "branch_pr_mode": "draft",
        "branch_history": "merge",
        "branch_squash_message": "deterministic",
        "branch_pr_strategy": "on-parent-approved",
    }
