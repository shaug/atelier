from pathlib import Path

import pytest

import atelier.workspace as workspace


def test_normalize_workspace_name_strips_and_normalizes() -> None:
    assert workspace.normalize_workspace_name(" feat/demo ") == "feat/demo"
    assert workspace.normalize_workspace_name("feat\\demo") == "feat/demo"


def test_normalize_workspace_name_rejects_absolute_paths() -> None:
    with pytest.raises(SystemExit):
        workspace.normalize_workspace_name("/abs/path")


def test_workspace_candidate_branches_applies_prefix() -> None:
    candidates = workspace.workspace_candidate_branches("feat/demo", "scott/", False)
    assert candidates == ["scott/feat/demo", "feat/demo"]


def test_workspace_environment_preserves_agent_identity_from_base_env(tmp_path: Path) -> None:
    env = workspace.workspace_environment(
        "/Users/scott/code/atelier",
        "scott/feature/test",
        tmp_path,
        base_env={
            "ATELIER_AGENT_ID": "atelier/worker/codex/p100",
            "ATELIER_PROJECT": "/tmp/other-project",
            "ATELIER_WORKSPACE": "other/branch",
            "ATELIER_MODE": "auto",
            "PATH": "/usr/bin",
        },
    )

    assert env["ATELIER_AGENT_ID"] == "atelier/worker/codex/p100"
    assert env["ATELIER_MODE"] == "auto"
    assert env["PATH"] == "/usr/bin"
    assert env["ATELIER_PROJECT"] == "/Users/scott/code/atelier"
    assert env["ATELIER_WORKSPACE"] == "scott/feature/test"
    assert env["ATELIER_WORKSPACE_DIR"] == str(tmp_path)


def test_workspace_environment_drops_ambient_agent_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/worker/codex/p100")

    env = workspace.workspace_environment(
        "/Users/scott/code/atelier",
        "scott/feature/test",
        tmp_path,
    )

    assert "ATELIER_AGENT_ID" not in env
