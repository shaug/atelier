from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess
from typing import cast

import pytest

from atelier.beads_runtime import client as runtime_client


@dataclass
class _RuntimeClient:
    json_payload: object = field(default_factory=list)
    command_result: CompletedProcess[str] = field(
        default_factory=lambda: CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")
    )
    shown_issue: dict[str, object] | None = None
    created_issue_id: str = "at-1"
    updated_issue: tuple[str, str] | None = None
    beads_root: Path = Path("/beads")
    cwd: Path = Path("/repo")

    def issue_write_lock(self, issue_id: str):
        del issue_id
        return nullcontext()

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        del issue_id
        return self.shown_issue

    def create_issue_with_body(self, args: list[str], description: str) -> str:
        del args, description
        return self.created_issue_id

    def update_issue_description(self, issue_id: str, description: str) -> None:
        self.updated_issue = (issue_id, description)

    def bd(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        del args, allow_failure
        if json_mode:
            return cast(list[dict[str, object]], self.json_payload)
        return self.command_result


def test_run_json_returns_rows() -> None:
    payload = [{"id": "at-1"}]
    client = _RuntimeClient(json_payload=payload)

    result = runtime_client.run_json(client, ["show", "at-1"])

    assert result == payload


def test_run_json_raises_on_non_list_payload() -> None:
    client = _RuntimeClient(
        json_payload=CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")
    )

    with pytest.raises(RuntimeError, match="expected JSON payload"):
        runtime_client.run_json(client, ["show", "at-1"])


def test_run_command_returns_process() -> None:
    process = CompletedProcess(args=["bd"], returncode=0, stdout="ok", stderr="")
    client = _RuntimeClient(command_result=process)

    result = runtime_client.run_command(client, ["show", "at-1"])

    assert result is process


def test_run_command_raises_on_json_payload() -> None:
    @dataclass
    class _InvalidRuntimeClient(_RuntimeClient):
        def bd(
            self,
            args: list[str],
            *,
            json_mode: bool = False,
            allow_failure: bool = False,
        ) -> CompletedProcess[str] | list[dict[str, object]]:
            del args, json_mode, allow_failure
            return [{"id": "at-1"}]

    client = _InvalidRuntimeClient()

    with pytest.raises(RuntimeError, match="expected command result"):
        runtime_client.run_command(client, ["update", "at-1"])


def test_runtime_client_delegates_show_create_update_helpers() -> None:
    shown = {"id": "at-7"}
    client = _RuntimeClient(shown_issue=shown, created_issue_id="at-8")

    assert runtime_client.show_issue(client, "at-7") == shown
    assert runtime_client.create_issue_with_body(client, ["create"], "desc") == "at-8"
    runtime_client.update_issue_description(client, "at-7", "next")
    assert client.updated_issue == ("at-7", "next")
