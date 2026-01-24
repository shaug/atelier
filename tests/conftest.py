# ruff: noqa: E402

import builtins
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import atelier.agents as agents
import atelier.io as io


@pytest.fixture(autouse=True)
def _default_agent_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agents, "available_agent_names", lambda: ("codex", "claude"))
    monkeypatch.setattr(io, "_use_questionary", lambda: False)

    def fail_input(prompt: str = "") -> str:
        raise AssertionError("prompted unexpectedly")

    monkeypatch.setattr(builtins, "input", fail_input)
