from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "work-done"
        / "scripts"
        / "close_epic.py"
    )
    spec = importlib.util.spec_from_file_location("work_done_close_epic", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_close_epic_uses_readiness_path(monkeypatch) -> None:
    module = _load_script_module()
    captured: dict[str, object] = {}

    def fake_close_epic_if_complete(
        epic_id: str,
        agent_bead_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> bool:
        captured["epic_id"] = epic_id
        captured["agent_bead_id"] = agent_bead_id
        captured["beads_root"] = beads_root
        captured["cwd"] = cwd
        return True

    monkeypatch.setattr(module.beads, "close_epic_if_complete", fake_close_epic_if_complete)
    monkeypatch.setattr(
        module.beads,
        "close_issue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected direct close")),
    )

    closed = module.close_epic(
        epic_id="at-epic",
        agent_bead_id="at-agent",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        direct_close=False,
    )

    assert closed is True
    assert captured == {
        "epic_id": "at-epic",
        "agent_bead_id": "at-agent",
        "beads_root": Path("/beads"),
        "cwd": Path("/repo"),
    }


def test_close_epic_direct_close_reconciles_and_clears_hook(monkeypatch) -> None:
    module = _load_script_module()
    events: list[tuple[str, str]] = []

    def fake_close_issue(
        issue_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> object:
        events.append(("close", issue_id))
        assert beads_root == Path("/beads")
        assert cwd == Path("/repo")
        return object()

    def fake_clear_agent_hook(agent_bead_id: str, *, beads_root: Path, cwd: Path) -> None:
        events.append(("clear_hook", agent_bead_id))
        assert beads_root == Path("/beads")
        assert cwd == Path("/repo")

    monkeypatch.setattr(module.beads, "close_issue", fake_close_issue)
    monkeypatch.setattr(module.beads, "clear_agent_hook", fake_clear_agent_hook)
    monkeypatch.setattr(
        module.beads,
        "close_epic_if_complete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected readiness close")
        ),
    )

    closed = module.close_epic(
        epic_id="at-epic",
        agent_bead_id="at-agent",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        direct_close=True,
    )

    assert closed is True
    assert events == [
        ("close", "at-epic"),
        ("clear_hook", "at-agent"),
    ]
