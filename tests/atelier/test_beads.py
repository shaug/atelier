from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import atelier.beads as beads


def test_ensure_agent_bead_returns_existing() -> None:
    existing = {"id": "atelier-1", "title": "agent"}
    with patch("atelier.beads.find_agent_bead", return_value=existing):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo")
        )
    assert result == existing


def test_ensure_agent_bead_creates_when_missing() -> None:
    def fake_command(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=["bd"], returncode=0, stdout="atelier-2\n", stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[0] == "show":
            return [{"id": "atelier-2", "title": "agent"}]
        return []

    with (
        patch("atelier.beads.find_agent_bead", return_value=None),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo"), role="worker"
        )

    assert result["id"] == "atelier-2"
