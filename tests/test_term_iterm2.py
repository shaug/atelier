import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atelier.term.base import WorkspaceState  # noqa: E402
from atelier.term.iterm2 import Iterm2Adapter  # noqa: E402


class FakeStdout:
    def __init__(self, isatty: bool) -> None:
        self._isatty = isatty
        self.buffer = ""

    def isatty(self) -> bool:
        return self._isatty

    def write(self, data: str) -> None:
        self.buffer += data

    def flush(self) -> None:
        return None


def test_set_pane_title_writes_osc1(monkeypatch):
    fake = FakeStdout(True)
    monkeypatch.setattr(sys, "stdout", fake)
    adapter = Iterm2Adapter()
    assert adapter.set_pane_title("repo:branch") is True
    assert fake.buffer == "\033]1;repo:branch\007"


def test_set_workspace_state_writes_osc1_and_osc2(monkeypatch):
    fake = FakeStdout(True)
    monkeypatch.setattr(sys, "stdout", fake)
    adapter = Iterm2Adapter()
    state = WorkspaceState(
        project="repo",
        branch="feat/demo",
        title="repo:feat/demo",
    )
    assert adapter.set_workspace_state(state) is True
    assert fake.buffer == "\033]1;repo:feat/demo\007\033]2;repo:feat/demo\007"


def test_set_pane_title_no_tty(monkeypatch):
    fake = FakeStdout(False)
    monkeypatch.setattr(sys, "stdout", fake)
    adapter = Iterm2Adapter()
    assert adapter.set_pane_title("repo:branch") is False
    assert fake.buffer == ""
