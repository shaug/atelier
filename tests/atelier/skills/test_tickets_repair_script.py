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
        / "tickets"
        / "scripts"
        / "repair_external_ticket_metadata.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tickets_repair_external_ticket_metadata", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repair_external_ticket_metadata_script_uses_compatibility_seam(
    monkeypatch,
    capsys,
) -> None:
    module = _load_script_module()
    calls: list[dict[str, object]] = []

    def fake_repair_external_ticket_metadata_from_history(
        *,
        beads_root: Path,
        repo_root: Path,
        issue_ids: list[str] | None = None,
        apply: bool = False,
    ) -> list[object]:
        calls.append(
            {
                "beads_root": beads_root,
                "repo_root": repo_root,
                "issue_ids": issue_ids,
                "apply": apply,
            }
        )
        return [
            SimpleNamespace(
                issue_id="at-123",
                repaired=False,
                recovered=True,
                ticket_count=2,
                providers=["github"],
            )
        ]

    monkeypatch.setattr(
        module,
        "external_ticket_repair_compat",
        SimpleNamespace(
            ExternalTicketMetadataRepairResult=object,
            repair_external_ticket_metadata_from_history=fake_repair_external_ticket_metadata_from_history,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_external_ticket_metadata.py",
            "--issue-id",
            "at-123",
            "--beads-dir",
            "/beads",
            "--apply",
        ],
    )

    repo_root = Path.cwd()
    module.main()
    captured = capsys.readouterr()

    assert calls == [
        {
            "beads_root": Path("/beads"),
            "repo_root": repo_root,
            "issue_ids": ["at-123"],
            "apply": True,
        }
    ]
    assert (
        "external_tickets repair (applied): total=1 repaired=0 recoverable=1 unrecoverable=0"
        in captured.out
    )
    assert "- at-123: recoverable (2 ticket(s), providers=github)" in captured.out
