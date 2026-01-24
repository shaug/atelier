import os
from pathlib import Path

import atelier.cli as cli
import atelier.config as config


def test_completion_env_uses_comp_line(monkeypatch):
    monkeypatch.setenv("_ATELIER_COMPLETE", "zsh_complete")
    monkeypatch.setenv("COMP_LINE", "atelier open rus")
    monkeypatch.setenv("COMP_POINT", str(len("atelier open rus")))
    monkeypatch.delenv("COMP_WORDS", raising=False)
    monkeypatch.delenv("COMP_CWORD", raising=False)

    cli._ensure_completion_env()

    assert os.environ["COMP_WORDS"] == "atelier open rus"
    assert os.environ["COMP_CWORD"] == "2"


def test_completion_env_handles_trailing_space(monkeypatch):
    monkeypatch.setenv("_ATELIER_COMPLETE", "zsh_complete")
    monkeypatch.setenv("COMP_LINE", "atelier open ")
    monkeypatch.setenv("COMP_POINT", str(len("atelier open ")))
    monkeypatch.delenv("COMP_WORDS", raising=False)
    monkeypatch.delenv("COMP_CWORD", raising=False)

    cli._ensure_completion_env()

    assert os.environ["COMP_WORDS"] == "atelier open "
    assert os.environ["COMP_CWORD"] == "2"


def test_completion_env_fallbacks_to_prog(monkeypatch):
    monkeypatch.setenv("_ATELIER_COMPLETE", "zsh_complete")
    monkeypatch.delenv("COMP_WORDS", raising=False)
    monkeypatch.delenv("COMP_CWORD", raising=False)
    monkeypatch.delenv("COMP_LINE", raising=False)
    monkeypatch.delenv("COMP_POINT", raising=False)
    monkeypatch.setattr(cli.sys, "argv", ["atelier"])

    cli._ensure_completion_env()

    assert os.environ["COMP_WORDS"] == "atelier"
    assert os.environ["COMP_CWORD"] == "0"


def test_workspace_completion_returns_empty_without_project(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_completion_project", lambda: None)

    assert cli._workspace_name_shell_complete(None, None, "") == []


def test_workspace_completion_filters_and_dedupes(monkeypatch):
    config_payload = config.ProjectConfig()
    monkeypatch.setattr(
        cli,
        "_resolve_completion_project",
        lambda: (Path("/repo"), Path("/project"), config_payload, None),
    )
    monkeypatch.setattr(
        cli.workspace,
        "collect_workspaces",
        lambda *args, **kwargs: [{"name": "feat/one"}, {"name": "bug/two"}],
    )
    monkeypatch.setattr(
        cli,
        "_collect_local_branches",
        lambda *args, **kwargs: ["bug/two", "chore/three"],
    )

    assert cli._workspace_name_shell_complete(None, None, "b") == ["bug/two"]


def test_workspace_completion_excludes_default_branches(monkeypatch):
    config_payload = config.ProjectConfig()
    monkeypatch.setattr(
        cli,
        "_resolve_completion_project",
        lambda: (Path("/repo"), Path("/project"), config_payload, None),
    )
    monkeypatch.setattr(
        cli.workspace,
        "collect_workspaces",
        lambda *args, **kwargs: [{"name": "main"}, {"name": "master"}],
    )
    monkeypatch.setattr(
        cli, "_collect_local_branches", lambda *args, **kwargs: ["main", "master"]
    )

    assert cli._workspace_name_shell_complete(None, None, "m") == []
