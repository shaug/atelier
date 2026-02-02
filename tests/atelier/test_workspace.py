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
