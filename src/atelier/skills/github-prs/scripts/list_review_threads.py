#!/usr/bin/env python3
"""List unresolved GitHub PR review threads and latest inline comments."""

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


def query_threads(repo: str, pr_number: int) -> list[dict[str, object]]:
    owner, name = _gh.split_repo_slug(repo)
    query = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
          comments(first: 100) {
            nodes {
              id
              databaseId
              body
              path
              line
              createdAt
              updatedAt
              author { login isBot }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""".strip()
    cursor: str | None = None
    rows: list[dict[str, object]] = []

    while True:
        cmd = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor:
            cmd.extend(["-F", f"cursor={cursor}"])
        payload = _gh.run_json(cmd)
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected graphql output for review threads")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Missing graphql data payload")
        repository = data.get("repository")
        if not isinstance(repository, dict):
            break
        pull_request = repository.get("pullRequest")
        if not isinstance(pull_request, dict):
            break
        review_threads = pull_request.get("reviewThreads")
        if not isinstance(review_threads, dict):
            break
        nodes = review_threads.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict):
                    rows.append(node)
        page_info = review_threads.get("pageInfo")
        has_next = False
        next_cursor = None
        if isinstance(page_info, dict):
            has_next = bool(page_info.get("hasNextPage"))
            raw_cursor = page_info.get("endCursor")
            if isinstance(raw_cursor, str) and raw_cursor:
                next_cursor = raw_cursor
        if not has_next:
            break
        cursor = next_cursor
        if not cursor:
            break

    return rows


def normalize_threads(
    threads: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for thread in threads:
        if bool(thread.get("isResolved")):
            continue
        comments = thread.get("comments")
        latest: dict[str, object] | None = None
        if isinstance(comments, dict):
            nodes = comments.get("nodes")
            if isinstance(nodes, list):
                for comment in nodes:
                    if not isinstance(comment, dict):
                        continue
                    if latest is None:
                        latest = comment
                        continue
                    current = str(
                        comment.get("updatedAt") or comment.get("createdAt") or ""
                    )
                    previous = str(
                        latest.get("updatedAt") or latest.get("createdAt") or ""
                    )
                    if current >= previous:
                        latest = comment
        if latest is None:
            continue
        normalized.append(
            {
                "thread_id": thread.get("id"),
                "comment_id": latest.get("databaseId"),
                "path": latest.get("path"),
                "line": latest.get("line"),
                "author": (
                    latest.get("author", {}).get("login")
                    if isinstance(latest.get("author"), dict)
                    else None
                ),
                "body": latest.get("body"),
                "created_at": latest.get("createdAt"),
                "updated_at": latest.get("updatedAt"),
            }
        )
    return normalized


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(
        description="List unresolved PR review threads with latest inline comment."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo slug (owner/name)")
    parser_group = parser.add_mutually_exclusive_group(required=True)
    parser_group.add_argument("--pr-number", type=int, help="PR number")
    parser_group.add_argument("--head", help="Head branch; resolves latest PR number")
    args = parser.parse_args(list(argv))

    try:
        pr_number = args.pr_number
        if pr_number is None:
            resolved = _gh.find_latest_pr_number(args.repo, args.head)
            if resolved is None:
                raise RuntimeError("No PR found for the head branch")
            pr_number = resolved
        threads = query_threads(args.repo, pr_number)
        payload = {
            "repo": args.repo,
            "pr_number": pr_number,
            "unresolved_threads": normalize_threads(threads),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
