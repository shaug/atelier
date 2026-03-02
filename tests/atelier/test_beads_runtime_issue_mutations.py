from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atelier.beads_runtime import issue_mutations


@dataclass
class _IssueMutationsClient(issue_mutations.IssueMutationsClient):
    issues: dict[str, dict[str, object]]
    interleaved: list[str] = field(default_factory=list)
    writes: int = 0

    def issue_write_lock(self, issue_id: str, beads_root: Path):
        del issue_id, beads_root
        return nullcontext()

    def read_issue(
        self,
        issue_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object] | None:
        del beads_root, cwd
        issue = self.issues.get(issue_id)
        if issue is None:
            return None
        return dict(issue)

    def update_issue_description(
        self,
        issue_id: str,
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        del beads_root, cwd
        self.writes += 1
        if self.interleaved:
            self.issues[issue_id] = {
                "id": issue_id,
                "description": self.interleaved.pop(0),
            }
            return
        self.issues[issue_id] = {"id": issue_id, "description": description}

    def die(self, message: str) -> None:
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
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        client=client,
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
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            client=client,
            description_update_max_attempts=3,
        )


def test_issue_description_fields_returns_empty_for_missing_issue() -> None:
    client = _IssueMutationsClient(issues={})

    result = issue_mutations.issue_description_fields(
        "missing",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        client=client,
    )

    assert result == {}
