import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atelier.term.wezterm import WezTermAdapter  # noqa: E402


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


def test_set_pane_title_writes_osc(monkeypatch):
    fake = FakeStdout(True)
    monkeypatch.setattr(sys, "stdout", fake)
    adapter = WezTermAdapter(pane_id="1")
    assert adapter.set_pane_title("repo:branch") is True
    assert fake.buffer == "\033]2;repo:branch\007"


def test_set_pane_title_no_tty(monkeypatch):
    fake = FakeStdout(False)
    monkeypatch.setattr(sys, "stdout", fake)
    adapter = WezTermAdapter(pane_id="1")
    assert adapter.set_pane_title("repo:branch") is False
    assert fake.buffer == ""
