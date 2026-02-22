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
        / "publish"
        / "scripts"
        / "repair_dependency_lineage.py"
    )
    spec = importlib.util.spec_from_file_location("repair_dependency_lineage", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_epic_reports_fixable_collapsed_parent_lineage() -> None:
    module = _load_script_module()
    changesets = [
        {
            "id": "at-epic.1",
            "description": "changeset.work_branch: feat/at-epic.1\n",
        },
        {
            "id": "at-epic.2",
            "description": (
                "changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"
            ),
            "dependencies": ["at-epic.1"],
        },
    ]

    report = module._evaluate_epic(epic_id="at-epic", changesets=changesets)

    assert len(report) == 1
    assert report[0].changeset_id == "at-epic.2"
    assert report[0].can_repair is True
    assert report[0].resolved_parent == "feat/at-epic.1"


def test_evaluate_epic_reports_ambiguous_dependency_lineage_as_blocked() -> None:
    module = _load_script_module()
    changesets = [
        {
            "id": "at-epic.1",
            "description": "changeset.work_branch: feat/at-epic.1\n",
        },
        {
            "id": "at-epic.2",
            "description": "changeset.work_branch: feat/at-epic.2\n",
        },
        {
            "id": "at-epic.3",
            "description": (
                "changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"
            ),
            "dependencies": ["at-epic.1", "at-epic.2"],
        },
    ]

    report = module._evaluate_epic(epic_id="at-epic", changesets=changesets)

    assert len(report) == 1
    assert report[0].changeset_id == "at-epic.3"
    assert report[0].blocked is True
    assert report[0].can_repair is False
