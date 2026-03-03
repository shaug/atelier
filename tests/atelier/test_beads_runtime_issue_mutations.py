from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess
from typing import NoReturn

import pytest

from atelier.beads_runtime import issue_mutations


@dataclass
class _IssueMutationsClient:
    issues: dict[str, dict[str, object]]
    interleaved: list[str] = field(default_factory=list)
    writes: int = 0
    beads_root: Path = Path("/beads")
    cwd: Path = Path("/repo")

    def issue_write_lock(self, issue_id: str):
        del issue_id
        return nullcontext()

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        issue = self.issues.get(issue_id)
        return dict(issue) if issue else None

    def create_issue_with_body(self, args: list[str], description: str) -> str:
        del args, description
        raise RuntimeError("not used")

    def update_issue_description(self, issue_id: str, description: str) -> None:
        self.writes += 1
        if self.interleaved:
            self.issues[issue_id] = {
                "id": issue_id,
                "description": self.interleaved.pop(0),
            }
            return
        self.issues[issue_id] = {"id": issue_id, "description": description}

    def bd(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        del allow_failure
        if json_mode:
            if args[:1] == ["show"] and len(args) >= 2:
                issue = self.issues.get(args[1])
                return [dict(issue)] if issue else []
            return []
        if args[:1] == ["update"] and "--body-file" in args and len(args) >= 2:
            issue_id = args[1]
            body_file = args[args.index("--body-file") + 1]
            self.update_issue_description(
                issue_id,
                Path(body_file).read_text(encoding="utf-8"),
            )
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def _fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def test_parse_description_fields_reads_key_values() -> None:
    parsed = issue_mutations.parse_description_fields("a: one\nb: two\n")

    assert parsed == {"a": "one", "b": "two"}


def test_update_issue_description_fields_retries_after_interleaved_overwrite() -> None:
    client = _IssueMutationsClient(
        issues={
            "agent-1": {"id": "agent-1", "description": "hook_bead: epic-1\npr_state: draft-pr\n"}
        },
        interleaved=["pr_state: in-review\n"],
    )

    updated = issue_mutations.update_issue_description_fields(
        "agent-1",
        {"hook_bead": "epic-2"},
        client=client,
        fail=_fail,
        description_update_max_attempts=3,
    )

    description = str(updated.get("description") or "")
    assert "hook_bead: epic-2" in description
    assert "pr_state: in-review" in description
    assert client.writes == 2


def test_update_issue_description_fields_fails_closed_after_retry_exhaustion() -> None:
    client = _IssueMutationsClient(
        issues={"agent-1": {"id": "agent-1", "description": "hook_bead: epic-1\n"}},
        interleaved=["hook_bead: epic-1\n"] * 3,
    )

    with pytest.raises(RuntimeError, match="concurrent description update conflict for agent-1"):
        issue_mutations.update_issue_description_fields(
            "agent-1",
            {"hook_bead": "epic-2"},
            client=client,
            fail=_fail,
            description_update_max_attempts=3,
        )


def test_issue_description_fields_returns_empty_for_missing_issue() -> None:
    client = _IssueMutationsClient(issues={})

    result = issue_mutations.issue_description_fields(
        "missing",
        client=client,
    )

    assert result == {}
