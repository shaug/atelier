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
        / "mail-mark-read"
        / "scripts"
        / "mark_message_read.py"
    )
    spec = importlib.util.spec_from_file_location("mail_mark_read_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mark_message_read_uses_store_request(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    class FakeStore:
        async def mark_message_read(self, request):
            captured["request"] = request
            return SimpleNamespace(id="msg-1")

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(sys, "argv", ["mark_message_read.py", "--message-id", "msg-1"])

    module.main()

    assert captured["request"].message_id == "msg-1"


def test_mark_message_read_surfaces_store_error(
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

    class FakeStore:
        async def mark_message_read(self, request):
            del request
            raise RuntimeError("message not found: msg-404")

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(sys, "argv", ["mark_message_read.py", "--message-id", "msg-404"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "message not found: msg-404" in capsys.readouterr().err
