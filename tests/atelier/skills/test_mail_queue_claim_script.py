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

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.setattr(module, "_resolve_claimed_by", lambda _explicit: "atelier/planner/codex/p1")

    class FakeStore:
        async def list_messages(self, query):
            del query
            return (SimpleNamespace(id="msg-1", queue="planner"),)

        async def claim_message(self, request):
            captured["request"] = request
            return SimpleNamespace(
                id="msg-1",
                claimed_by="atelier/planner/codex/p1",
                queue="planner",
                status=SimpleNamespace(value="open"),
                claimed_at="2026-03-14T22:00:00Z",
            )

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        sys,
        "argv",
        ["claim_message.py", "--message-id", "msg-1", "--queue", "planner"],
    )

    module.main()

    assert captured["request"].message_id == "msg-1"
    assert captured["request"].claimed_by == "atelier/planner/codex/p1"


def test_claim_message_rejects_queue_mismatch(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.setattr(module, "_resolve_claimed_by", lambda _explicit: "atelier/planner/codex/p1")

    class FakeStore:
        async def list_messages(self, query):
            del query
            return (SimpleNamespace(id="msg-1", queue="operator"),)

        async def claim_message(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        sys,
        "argv",
        ["claim_message.py", "--message-id", "msg-1", "--queue", "planner"],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "message msg-1 is not in queue 'planner'" in capsys.readouterr().err
