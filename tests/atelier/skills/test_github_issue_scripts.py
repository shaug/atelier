from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


def _load_script(filename: str):
    scripts_dir = Path(__file__).resolve().parents[3] / "src/atelier/skills/github-issues/scripts"
    path = scripts_dir / filename
    module_name = f"test_{filename.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_issue_script_uses_body_file(capsys) -> None:
    module = _load_script("create_issue.py")
    observed: dict[str, object] = {}

    def fake_run_gh(args: list[str]) -> str:
        if args[:2] == ["issue", "create"]:
            body_index = args.index("--body-file")
            body_path = Path(args[body_index + 1])
            observed["body"] = body_path.read_text(encoding="utf-8")
            observed["body_path"] = body_path
            observed["body_exists_during_call"] = body_path.exists()
            return "https://github.com/org/repo/issues/123\n"
        if args[:2] == ["issue", "view"]:
            return json.dumps(
                {
                    "number": 123,
                    "title": "Title with `ticks` and $(echo safe)",
                    "body": "Body with `code` and $(echo safe)",
                    "state": "OPEN",
                    "url": "https://github.com/org/repo/issues/123",
                    "labels": [],
                    "assignees": [],
                    "author": {"login": "tester"},
                }
            )
        raise AssertionError(f"unexpected args: {args}")

    with (
        patch.object(
            module.sys,
            "argv",
            [
                "create_issue.py",
                "--repo",
                "org/repo",
                "--title",
                "Title with `ticks` and $(echo safe)",
                "--body",
                "Body with `code` and $(echo safe)",
            ],
        ),
        patch.object(module, "run_gh", side_effect=fake_run_gh),
    ):
        module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["number"] == 123
    assert observed["body_exists_during_call"] is True
    assert observed["body"] == "Body with `code` and $(echo safe)"
    body_path = observed["body_path"]
    assert isinstance(body_path, Path)
    assert not body_path.exists()


def test_update_issue_script_uses_body_file(capsys) -> None:
    module = _load_script("update_issue.py")
    observed: dict[str, object] = {}

    def fake_run_gh(args: list[str]) -> str:
        if args[:2] == ["issue", "edit"]:
            body_index = args.index("--body-file")
            body_path = Path(args[body_index + 1])
            observed["body"] = body_path.read_text(encoding="utf-8")
            observed["body_path"] = body_path
            observed["body_exists_during_call"] = body_path.exists()
            return ""
        if args[:2] == ["issue", "view"]:
            return json.dumps(
                {
                    "number": 44,
                    "title": "Title with `ticks` and $(echo safe)",
                    "body": "Body with `code` and $(echo safe)",
                    "state": "OPEN",
                    "url": "https://github.com/org/repo/issues/44",
                    "labels": [],
                    "assignees": [],
                    "author": {"login": "tester"},
                }
            )
        raise AssertionError(f"unexpected args: {args}")

    with (
        patch.object(
            module.sys,
            "argv",
            [
                "update_issue.py",
                "--repo",
                "org/repo",
                "--issue",
                "44",
                "--title",
                "Title with `ticks` and $(echo safe)",
                "--body",
                "Body with `code` and $(echo safe)",
            ],
        ),
        patch.object(module, "run_gh", side_effect=fake_run_gh),
    ):
        module.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["number"] == 44
    assert observed["body_exists_during_call"] is True
    assert observed["body"] == "Body with `code` and $(echo safe)"
    body_path = observed["body_path"]
    assert isinstance(body_path, Path)
    assert not body_path.exists()
