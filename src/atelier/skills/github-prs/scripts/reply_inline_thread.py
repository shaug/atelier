#!/usr/bin/env python3
"""Reply inline to a PR review comment and resolve its review thread."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _gh  # type: ignore[import-not-found]
else:  # pragma: no cover
    from . import _gh


def reply_inline_comment(repo: str, comment_id: int, body: str) -> dict[str, object]:
    payload = _gh.run_json(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls/comments/{comment_id}/replies",
            "-f",
            f"body={body}",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected response when creating inline reply")
    return payload


def resolve_review_thread(thread_id: str) -> dict[str, object]:
    query = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
""".strip()
    payload = _gh.run_json(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"threadId={thread_id}",
        ]
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected response when resolving review thread")
    return payload


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reply inline to a PR review comment and optionally resolve the thread."
        )
    )
    parser.add_argument("--repo", required=True, help="GitHub repo slug (owner/name)")
    parser.add_argument(
        "--comment-id", required=True, type=int, help="Inline review comment id"
    )
    parser.add_argument(
        "--thread-id",
        help="GraphQL review thread id to resolve after reply (optional)",
    )
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", help="Reply body text")
    body_group.add_argument("--body-file", help="Path to reply body file (UTF-8 text)")
    args = parser.parse_args(list(argv))

    try:
        if args.body_file:
            body = open(args.body_file, encoding="utf-8").read()
        else:
            body = args.body or ""
        if not body.strip():
            raise RuntimeError("reply body must not be empty")
        reply = reply_inline_comment(args.repo, args.comment_id, body)
        resolved = None
        if args.thread_id:
            resolved = resolve_review_thread(args.thread_id)
        print(
            json.dumps(
                {
                    "reply_id": reply.get("id"),
                    "reply_url": reply.get("html_url"),
                    "thread_resolved": bool(
                        isinstance(resolved, dict)
                        and isinstance(resolved.get("data"), dict)
                        and isinstance(
                            resolved.get("data", {}).get("resolveReviewThread"), dict
                        )
                        and isinstance(
                            resolved.get("data", {})
                            .get("resolveReviewThread", {})
                            .get("thread"),
                            dict,
                        )
                        and bool(
                            resolved.get("data", {})
                            .get("resolveReviewThread", {})
                            .get("thread", {})
                            .get("isResolved")
                        )
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
