from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "mail-queue-claim"
        / "scripts"
        / "claim_message.py"
    )
    spec = importlib.util.spec_from_file_location("mail_queue_claim_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_claim_message_uses_store_request(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    captured: dict[str, object] = {}
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()

    class FakeStore:
        async def claim_message(self, request):
            captured["request"] = request
            return SimpleNamespace(
                id="msg-1",
                claimed_by="atelier/planner/codex/p1",
                queue="planner",
                claimed_at="2026-03-14T22:00:00Z",
                thread_id="at-epic.1",
                thread_kind=SimpleNamespace(value="changeset"),
            )

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())

    result = module.claim_message(
        message_id="msg-1",
        claimed_by="atelier/planner/codex/p1",
        queue="planner",
        beads_root=beads_root,
        repo_root=tmp_path / "repo",
    )

    assert captured["request"].message_id == "msg-1"
    assert captured["request"].claimed_by == "atelier/planner/codex/p1"
    assert captured["request"].queue == "planner"
    assert result["thread_kind"] == "changeset"


def test_claim_message_rejects_queue_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()

    class FakeStore:
        async def claim_message(self, request):
            raise ValueError(f"message {request.message_id} is not in queue {request.queue!r}")

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())

    with pytest.raises(ValueError, match="message msg-1 is not in queue 'planner'"):
        module.claim_message(
            message_id="msg-1",
            claimed_by="atelier/planner/codex/p1",
            queue="planner",
            beads_root=beads_root,
            repo_root=tmp_path / "repo",
        )
