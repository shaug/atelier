#!/usr/bin/env python3
"""Run publish skill integration evals using codex exec JSON logs."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PromptCase:
    case_id: str
    should_trigger: bool
    expected_commands: list[str]
    prompt: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_cases(path: Path) -> list[PromptCase]:
    cases: list[PromptCase] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            expected = [
                item.strip()
                for item in (row.get("expected_commands") or "").split(";")
                if item.strip()
            ]
            cases.append(
                PromptCase(
                    case_id=row["id"],
                    should_trigger=row["should_trigger"].strip().lower() == "true",
                    expected_commands=expected,
                    prompt=row["prompt"],
                )
            )
    return cases


def ensure_codex_available() -> None:
    if shutil.which("codex") is None:
        raise SystemExit("codex CLI not found on PATH")


def write_workspace_config(workspace: Path) -> None:
    config = {
        "workspace": {
            "branch": "feat/eval",
            "branch_pr": False,
            "branch_history": "rebase",
            "base": {"default_branch": "main"},
        }
    }
    (workspace / "config.sys.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (workspace / "config.user.json").write_text(json.dumps({}, indent=2), encoding="utf-8")
    (workspace / "SUCCESS.md").write_text(
        "# Success\n\nRun publish evals.\n",
        encoding="utf-8",
    )


def setup_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    skill_src = repo_root() / "src" / "atelier" / "skills" / "publish"
    skill_dest = workspace / "skills" / "publish"
    shutil.copytree(skill_src, skill_dest)
    repo_dir = workspace / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test User"], check=True)
    (repo_dir / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init"], check=True)
    write_workspace_config(workspace)


def run_case(case: PromptCase, artifacts_dir: Path) -> tuple[bool, str]:
    workspace = artifacts_dir / case.case_id / "workspace"
    setup_workspace(workspace)
    output_path = artifacts_dir / case.case_id / "trace.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["codex", "exec", "--json", "--full-auto", case.prompt],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    output_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        return False, f"codex exec failed: {result.stderr.strip()}"

    commands: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        item = payload.get("item") or {}
        if item.get("type") == "command_execution":
            command = item.get("command")
            if command:
                commands.append(command)

    triggered = any("resolve_publish_plan.py" in cmd for cmd in commands)
    if case.should_trigger and not triggered:
        return False, "expected publish skill to trigger"
    if not case.should_trigger and triggered:
        return False, "expected publish skill to not trigger"
    for expected in case.expected_commands:
        if not any(expected in cmd for cmd in commands):
            return False, f"expected command containing '{expected}'"
    return True, "ok"


def main() -> None:
    ensure_codex_available()
    root = repo_root()
    cases = load_cases(root / "evals" / "publish-skill.prompts.csv")
    artifacts = root / "evals" / "artifacts"
    failures: list[str] = []

    for case in cases:
        ok, message = run_case(case, artifacts)
        status = "PASS" if ok else "FAIL"
        print(f"{status} {case.case_id}: {message}")
        if not ok:
            failures.append(case.case_id)

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
