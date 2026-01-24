import os

import atelier.cli as cli


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
