from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


def _load_script(filename: str):
    scripts_dir = Path(__file__).resolve().parents[3] / "src/atelier/skills/github-prs/scripts"
    path = scripts_dir / filename
    module_name = f"test_{filename.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_list_review_threads_normalize_threads_uses_latest_unresolved_comment() -> None:
    module = _load_script("list_review_threads.py")
    threads = [
        {
            "id": "thread-open",
            "isResolved": False,
            "comments": {
                "nodes": [
                    {
                        "databaseId": 10,
                        "path": "a.py",
                        "line": 10,
                        "body": "old",
                        "createdAt": "2026-02-20T01:00:00Z",
                        "updatedAt": "2026-02-20T01:00:00Z",
                        "author": {"login": "reviewer"},
                    },
                    {
                        "databaseId": 11,
                        "path": "a.py",
                        "line": 12,
                        "body": "new",
                        "createdAt": "2026-02-20T01:05:00Z",
                        "updatedAt": "2026-02-20T01:05:00Z",
                        "author": {"login": "reviewer"},
                    },
                ]
            },
        },
        {
            "id": "thread-resolved",
            "isResolved": True,
            "comments": {"nodes": []},
        },
    ]

    normalized = module.normalize_threads(threads)
    assert len(normalized) == 1
    assert normalized[0]["thread_id"] == "thread-open"
    assert normalized[0]["comment_id"] == 11
    assert normalized[0]["line"] == 12


def test_list_review_threads_query_threads_paginates() -> None:
    module = _load_script("list_review_threads.py")
    payload_page_1 = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"id": "t1", "isResolved": False, "comments": {"nodes": []}}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    }
                }
            }
        }
    }
    payload_page_2 = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"id": "t2", "isResolved": False, "comments": {"nodes": []}}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    }

    with patch.object(
        module._gh, "run_json", side_effect=[payload_page_1, payload_page_2]
    ) as run_json:
        rows = module.query_threads("org/repo", 204)

    assert [row["id"] for row in rows] == ["t1", "t2"]
    assert run_json.call_count == 2


def test_reply_inline_thread_main_resolves_thread(capsys) -> None:
    module = _load_script("reply_inline_thread.py")
    with (
        patch.object(
            module,
            "reply_inline_comment",
            return_value={"id": 321, "html_url": "https://example/pr/comment/321"},
        ),
        patch.object(
            module,
            "resolve_review_thread",
            return_value={
                "data": {"resolveReviewThread": {"thread": {"id": "t1", "isResolved": True}}}
            },
        ),
    ):
        rc = module.main(
            [
                "--repo",
                "org/repo",
                "--comment-id",
                "123",
                "--thread-id",
                "t1",
                "--body",
                "Addressed inline.",
            ]
        )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reply_id"] == 321
    assert payload["thread_resolved"] is True


def test_reply_inline_thread_main_rejects_empty_body(capsys) -> None:
    module = _load_script("reply_inline_thread.py")
    rc = module.main(
        [
            "--repo",
            "org/repo",
            "--comment-id",
            "123",
            "--body",
            "   ",
        ]
    )
    assert rc == 1
    assert "reply body must not be empty" in capsys.readouterr().err


def test_create_or_update_pr_create_uses_body_file(capsys) -> None:
    module = _load_script("create_or_update_pr.py")
    observed: dict[str, object] = {}

    def fake_run(cmd: list[str]) -> str:
        if cmd[:3] != ["gh", "pr", "create"]:
            raise AssertionError(f"unexpected command: {cmd}")
        body_index = cmd.index("--body-file")
        body_path = Path(cmd[body_index + 1])
        observed["body"] = body_path.read_text(encoding="utf-8")
        observed["body_path"] = body_path
        observed["body_exists_during_call"] = body_path.exists()
        return "https://github.com/org/repo/pull/77\n"

    with (
        patch.object(module, "find_pr_number", return_value=None),
        patch.object(module, "edit_labels", return_value=None),
        patch.object(module, "read_pr", return_value={"number": 77, "title": "Draft"}),
        patch.object(module, "run", side_effect=fake_run),
    ):
        rc = module.main(
            [
                "--repo",
                "org/repo",
                "--base",
                "main",
                "--head",
                "feature/work",
                "--title",
                "Title with `ticks` and $(echo safe)",
                "--body",
                "Body with `code` and $(echo safe)",
                "--labels",
                "",
            ]
        )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["number"] == 77
    assert observed["body_exists_during_call"] is True
    assert observed["body"] == "Body with `code` and $(echo safe)"
    body_path = observed["body_path"]
    assert isinstance(body_path, Path)
    assert not body_path.exists()


def test_create_or_update_pr_edit_uses_body_file(capsys) -> None:
    module = _load_script("create_or_update_pr.py")
    observed: dict[str, object] = {}

    def fake_run(cmd: list[str]) -> str:
        if cmd[:3] != ["gh", "pr", "edit"]:
            raise AssertionError(f"unexpected command: {cmd}")
        body_index = cmd.index("--body-file")
        body_path = Path(cmd[body_index + 1])
        observed["body"] = body_path.read_text(encoding="utf-8")
        observed["body_path"] = body_path
        observed["body_exists_during_call"] = body_path.exists()
        return ""

    with (
        patch.object(module, "find_pr_number", return_value=41),
        patch.object(module, "edit_labels", return_value=None),
        patch.object(module, "read_pr", return_value={"number": 41, "title": "Draft"}),
        patch.object(module, "run", side_effect=fake_run),
    ):
        rc = module.main(
            [
                "--repo",
                "org/repo",
                "--base",
                "main",
                "--head",
                "feature/work",
                "--title",
                "Title with `ticks` and $(echo safe)",
                "--body",
                "Body with `code` and $(echo safe)",
                "--labels",
                "bug",
            ]
        )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["number"] == 41
    assert observed["body_exists_during_call"] is True
    assert observed["body"] == "Body with `code` and $(echo safe)"
    body_path = observed["body_path"]
    assert isinstance(body_path, Path)
    assert not body_path.exists()
