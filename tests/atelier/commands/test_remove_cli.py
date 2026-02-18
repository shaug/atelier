from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_remove_passes_args_to_command() -> None:
    captured: dict[str, object] = {}

    def fake_remove(args: SimpleNamespace) -> None:
        captured["yes"] = args.yes
        captured["dry_run"] = args.dry_run
        captured["gc"] = args.gc
        captured["reconcile"] = args.reconcile
        captured["prune_branches"] = args.prune_branches

    runner = CliRunner()
    with patch("atelier.commands.remove.remove_project", fake_remove):
        result = runner.invoke(
            cli.app,
            [
                "remove",
                "--yes",
                "--dry-run",
                "--no-gc",
                "--reconcile",
                "--prune-branches",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "yes": True,
        "dry_run": True,
        "gc": False,
        "reconcile": True,
        "prune_branches": True,
    }
