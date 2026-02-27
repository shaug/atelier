import os
from pathlib import Path
from types import SimpleNamespace

import atelier.cli as cli
import atelier.config as config


def test_completion_env_uses_comp_line(monkeypatch):
    monkeypatch.setenv("_ATELIER_COMPLETE", "zsh_complete")
    monkeypatch.setenv("COMP_LINE", "atelier work rus")
    monkeypatch.setenv("COMP_POINT", str(len("atelier work rus")))
    monkeypatch.delenv("COMP_WORDS", raising=False)
    monkeypatch.delenv("COMP_CWORD", raising=False)

    cli._ensure_completion_env()

    assert os.environ["COMP_WORDS"] == "atelier work rus"
    assert os.environ["COMP_CWORD"] == "2"


def test_completion_env_handles_trailing_space(monkeypatch):
    monkeypatch.setenv("_ATELIER_COMPLETE", "zsh_complete")
    monkeypatch.setenv("COMP_LINE", "atelier work ")
    monkeypatch.setenv("COMP_POINT", str(len("atelier work ")))
    monkeypatch.delenv("COMP_WORDS", raising=False)
    monkeypatch.delenv("COMP_CWORD", raising=False)

    cli._ensure_completion_env()

    assert os.environ["COMP_WORDS"] == "atelier work "
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


def test_workspace_only_completion_returns_empty_without_project(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_completion_project", lambda: None)

    assert cli._workspace_only_shell_complete(None, [], "") == []


def test_workspace_only_completion_returns_root_branches(monkeypatch):
    config_payload = config.ProjectConfig()
    monkeypatch.setattr(
        cli,
        "_resolve_completion_project",
        lambda: (Path("/repo"), Path("/project"), config_payload, None),
    )
    monkeypatch.setattr(
        cli,
        "_collect_workspace_root_branches",
        lambda *args, **kwargs: ["feat/one", "bug/two", "bug/two"],
    )

    assert cli._workspace_only_shell_complete(None, [], "b") == ["bug/two"]


def test_collect_workspace_root_branches_includes_hooked_active_labels(monkeypatch):
    payload = (
        '[{"id":"at-1","status":"hooked","labels":["at:epic","at:hooked"],'
        '"description":"workspace.root_branch: feat/hooked\\n"},'
        '{"id":"at-2","status":"closed","labels":["at:epic"],'
        '"description":"workspace.root_branch: feat/closed\\n"}]'
    )
    monkeypatch.setattr(
        cli,
        "try_run_command",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=payload),
    )

    names = cli._collect_workspace_root_branches(Path("/repo"), beads_root=Path("/beads"))

    assert names == ["feat/hooked"]
