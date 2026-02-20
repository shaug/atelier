from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


def _load_script(filename: str):
    scripts_dir = (
        Path(__file__).resolve().parents[3] / "src/atelier/skills/github-prs/scripts"
    )
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
                        "nodes": [
                            {"id": "t1", "isResolved": False, "comments": {"nodes": []}}
                        ],
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
                        "nodes": [
                            {"id": "t2", "isResolved": False, "comments": {"nodes": []}}
                        ],
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
                "data": {
                    "resolveReviewThread": {"thread": {"id": "t1", "isResolved": True}}
                }
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
