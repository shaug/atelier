# ruff: noqa: E402

import builtins
import sys
from pathlib import Path

import pytest
from _pytest.doctest import DoctestModule

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import atelier.agents as agents
import atelier.io as io

DOCTEST_MODULES = {
    ROOT / "src" / "atelier" / "__init__.py",
    ROOT / "src" / "atelier" / "config.py",
    ROOT / "src" / "atelier" / "editor.py",
    ROOT / "src" / "atelier" / "models.py",
    ROOT / "src" / "atelier" / "paths.py",
    ROOT / "src" / "atelier" / "templates.py",
}


@pytest.fixture(autouse=True)
def _default_agent_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agents, "available_agent_names", lambda: ("codex", "claude"))
    monkeypatch.setattr(io, "_use_questionary", lambda: False)

    def fail_input(prompt: str = "") -> str:
        raise AssertionError("prompted unexpectedly")

    monkeypatch.setattr(builtins, "input", fail_input)


def pytest_collect_file(
    parent: pytest.Collector, file_path: Path
) -> DoctestModule | None:
    path = file_path if isinstance(file_path, Path) else Path(str(file_path))
    if path in DOCTEST_MODULES:
        return DoctestModule.from_parent(parent, path=path)
    return None
