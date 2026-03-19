from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


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
        repo_root: Path,
    ) -> bool:
        captured["epic_id"] = epic_id
        captured["agent_bead_id"] = agent_bead_id
        captured["beads_root"] = beads_root
        captured["repo_root"] = repo_root
        return True

    monkeypatch.setattr(
        module,
        "_load_epic_close_runtime_for_execution",
        lambda: SimpleNamespace(
            close_epic_if_complete=fake_close_epic_if_complete,
            direct_close_epic=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("unexpected direct close")
            ),
        ),
    )

    closed = module.close_epic(
        epic_id="at-epic",
        agent_bead_id="at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        direct_close=False,
    )

    assert closed is True
    assert captured == {
        "epic_id": "at-epic",
        "agent_bead_id": "at-agent",
        "beads_root": Path("/beads"),
        "repo_root": Path("/repo"),
    }


def test_close_epic_direct_close_reconciles_and_clears_hook(monkeypatch) -> None:
    module = _load_script_module()
    events: list[tuple[str, str]] = []

    def fake_direct_close_epic(
        issue_id: str,
        agent_bead_id: str,
        *,
        beads_root: Path,
        repo_root: Path,
    ) -> None:
        events.append(("close", issue_id))
        events.append(("clear_hook", agent_bead_id))
        assert beads_root == Path("/beads")
        assert repo_root == Path("/repo")

    monkeypatch.setattr(
        module,
        "_load_epic_close_runtime_for_execution",
        lambda: SimpleNamespace(
            direct_close_epic=fake_direct_close_epic,
            close_epic_if_complete=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("unexpected readiness close")
            ),
        ),
    )

    closed = module.close_epic(
        epic_id="at-epic",
        agent_bead_id="at-agent",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        direct_close=True,
    )

    assert closed is True
    assert events == [
        ("close", "at-epic"),
        ("clear_hook", "at-agent"),
    ]


def test_main_uses_bootstrap_repo_root_for_execution(monkeypatch, tmp_path) -> None:
    module = _load_script_module()
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "_BOOTSTRAP_REPO_ROOT", Path("/bootstrap/repo"))
    monkeypatch.setattr(module, "close_epic", lambda **kwargs: captured.update(kwargs) or True)
    monkeypatch.setenv("BEADS_DIR", str(beads_root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "close_epic.py",
            "--epic-id",
            "at-epic",
            "--agent-bead-id",
            "at-agent",
        ],
    )

    module.main()

    assert captured == {
        "epic_id": "at-epic",
        "agent_bead_id": "at-agent",
        "beads_root": beads_root.resolve(),
        "repo_root": Path("/bootstrap/repo"),
        "direct_close": False,
    }
