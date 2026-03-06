from __future__ import annotations

import importlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.beads as beads
import atelier.prefix_migration_drift as prefix_migration_drift
import atelier.worktrees as worktrees
from atelier.worker.session import worktree as session_worktree

doctor_cmd = importlib.import_module("atelier.commands.doctor")


@dataclass(frozen=True)
class _ConvergenceCase:
    project_name: str
    epic_id: str
    changeset_id: str
    root_branch: str
    canonical_work_branch: str
    legacy_work_branch: str
    legacy_worktree_path: str


@dataclass
class _FixtureState:
    case: _ConvergenceCase
    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    epic_issue: dict[str, object]
    changeset_issue: dict[str, object]
    worktree_output: str


_CASES = (
    _ConvergenceCase(
        project_name="tuber-service",
        epic_id="ts-migration",
        changeset_id="ts-migration.1",
        root_branch="scott/tuber-service-prefix-convergence",
        canonical_work_branch="scott/tuber-service-prefix-convergence-ts-migration.1",
        legacy_work_branch="at/legacy-ts-migration.1",
        legacy_worktree_path="worktrees/at-legacy-ts-migration.1",
    ),
    _ConvergenceCase(
        project_name="gumshoe",
        epic_id="gs-migration",
        changeset_id="gs-migration.1",
        root_branch="scott/gumshoe-prefix-convergence",
        canonical_work_branch="scott/gumshoe-prefix-convergence-gs-migration.1",
        legacy_work_branch="at/legacy-gs-migration.1",
        legacy_worktree_path="worktrees/at-legacy-gs-migration.1",
    ),
    _ConvergenceCase(
        project_name="eldritchdark",
        epic_id="ed-migration",
        changeset_id="ed-migration.1",
        root_branch="scott/eldritchdark-prefix-convergence",
        canonical_work_branch="scott/eldritchdark-prefix-convergence-ed-migration.1",
        legacy_work_branch="at/legacy-ed-migration.1",
        legacy_worktree_path="worktrees/at-legacy-ed-migration.1",
    ),
)


def _git_worktree_output(path: Path, branch: str) -> str:
    return (
        f"worktree {path}\n"
        "HEAD 0123456789abcdef0123456789abcdef01234567\n"
        f"branch refs/heads/{branch}\n\n"
    )


def _prepare_fixture(tmp_path: Path, case: _ConvergenceCase) -> _FixtureState:
    project_data_dir = tmp_path / case.project_name / "data"
    repo_root = tmp_path / case.project_name / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)

    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, case.epic_id),
        worktrees.WorktreeMapping(
            epic_id=case.epic_id,
            worktree_path=f"worktrees/{case.epic_id}",
            root_branch=case.root_branch,
            changesets={case.changeset_id: case.legacy_work_branch},
            changeset_worktrees={case.changeset_id: case.legacy_worktree_path},
        ),
    )

    epic_issue: dict[str, object] = {
        "id": case.epic_id,
        "status": "in_progress",
        "assignee": "worker-test",
        "labels": ["at:epic"],
        "description": f"workspace.root_branch: {case.root_branch}\n",
    }
    changeset_issue: dict[str, object] = {
        "id": case.changeset_id,
        "status": "in_progress",
        "labels": [],
        "type": "task",
        "description": (
            f"changeset.root_branch: {case.root_branch}\n"
            f"changeset.work_branch: {case.canonical_work_branch}\n"
            f"worktree_path: worktrees/{case.changeset_id}-old\n"
        ),
    }

    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / case.changeset_id,
        case.canonical_work_branch,
    )

    return _FixtureState(
        case=case,
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        beads_root=tmp_path / case.project_name / ".beads",
        epic_issue=epic_issue,
        changeset_issue=changeset_issue,
        worktree_output=worktree_output,
    )


def _set_description_field(issue: dict[str, object], key: str, value: str) -> None:
    fields = beads.parse_description_fields(issue.get("description"))
    fields[key] = value
    issue["description"] = "".join(
        f"{field_key}: {field_value}\n" for field_key, field_value in fields.items()
    )


def _build_doctor_context(state: _FixtureState) -> object:
    mapping = worktrees.load_mapping(
        worktrees.mapping_path(state.project_data_dir, state.case.epic_id)
    )
    return doctor_cmd._DoctorContext(
        project_data_dir=state.project_data_dir,
        epics_by_id={state.case.epic_id: state.epic_issue},
        changesets=[state.changeset_issue],
        changeset_to_epic={state.case.changeset_id: state.case.epic_id},
        fields_by_changeset={
            state.case.changeset_id: beads.parse_description_fields(
                state.changeset_issue.get("description")
            )
        },
        mappings_by_epic={state.case.epic_id: mapping},
    )


@pytest.mark.parametrize("case", _CASES, ids=[case.project_name for case in _CASES])
def test_migrated_project_convergence_harness(case: _ConvergenceCase, tmp_path: Path) -> None:
    state = _prepare_fixture(tmp_path, case)

    def fake_show(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args == ["show", case.epic_id]:
            return [state.epic_issue]
        if args == ["show", case.changeset_id]:
            return [state.changeset_issue]
        raise AssertionError(f"unexpected bd command: {args!r}")

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == case.legacy_work_branch:
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": case.canonical_work_branch},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[state.epic_issue]),
        patch("atelier.prefix_migration_drift.beads.run_bd_json", side_effect=fake_show),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[state.changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=state.worktree_output,
                stderr="",
            ),
        ),
    ):
        drift_records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=state.project_data_dir,
            beads_root=state.beads_root,
            repo_root=state.repo_root,
        )

        assert {record["drift_class"] for record in drift_records} == {
            "work-branch-conflict",
            "worktree-path-conflict",
        }

        planned_actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=state.project_data_dir,
            beads_root=state.beads_root,
            repo_root=state.repo_root,
            apply=False,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )

        assert len(planned_actions) == 1
        planned = planned_actions[0]
        assert planned.changed is True
        assert planned.canonical_work_branch == case.canonical_work_branch
        assert planned.canonical_worktree_path == f"worktrees/{case.changeset_id}"

        checks_before = doctor_cmd._build_check_families(
            context=_build_doctor_context(state),
            actions=planned_actions,
            hook_map={},
            agent_index={},
            fix=False,
        )
        checks_before_by_id = {check.check_id: check for check in checks_before}
        startup_codes_before = {
            finding.code
            for finding in checks_before_by_id["startup_blocking_lineage_consistency"].findings
        }
        assert startup_codes_before >= {
            "metadata-work-branch-conflict",
            "metadata-worktree-path-conflict",
        }
        assert len(checks_before_by_id["prefix_migration_drift"].findings) == 1

        def fake_update_metadata(
            changeset_id: str,
            *,
            root_branch: str | None,
            parent_branch: str | None,
            work_branch: str | None,
            beads_root: Path,
            cwd: Path,
            allow_override: bool,
        ) -> None:
            del changeset_id, parent_branch, beads_root, cwd, allow_override
            if root_branch is not None:
                _set_description_field(state.changeset_issue, "changeset.root_branch", root_branch)
            if work_branch is not None:
                _set_description_field(state.changeset_issue, "changeset.work_branch", work_branch)

        def fake_update_worktree_path(
            changeset_id: str,
            worktree_path: str,
            *,
            beads_root: Path,
            cwd: Path,
            allow_override: bool,
        ) -> None:
            del changeset_id, beads_root, cwd, allow_override
            _set_description_field(state.changeset_issue, "worktree_path", worktree_path)

        with (
            patch(
                "atelier.prefix_migration_drift.beads.update_workspace_root_branch"
            ) as update_root,
            patch(
                "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata",
                side_effect=fake_update_metadata,
            ),
            patch(
                "atelier.prefix_migration_drift.beads.update_worktree_path",
                side_effect=fake_update_worktree_path,
            ),
            patch("atelier.worker.session.worktree.git.git_origin_url", return_value=None),
            patch("atelier.worker.session.worktree.prs.github_repo_slug", return_value=None),
        ):
            session_worktree._startup_worktree_preflight(
                project_data_dir=state.project_data_dir,
                beads_root=state.beads_root,
                repo_root=state.repo_root,
                selected_epic=case.epic_id,
                changeset_id=case.changeset_id,
                root_branch_value=case.root_branch,
                changeset_parent_branch=case.root_branch,
                allow_parent_branch_override=False,
                git_path=None,
            )
        update_root.assert_not_called()

        assert (
            prefix_migration_drift.scan_prefix_migration_drift(
                project_data_dir=state.project_data_dir,
                beads_root=state.beads_root,
                repo_root=state.repo_root,
            )
            == []
        )

        post_actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=state.project_data_dir,
            beads_root=state.beads_root,
            repo_root=state.repo_root,
            apply=False,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )

        assert post_actions == []

        checks_after = doctor_cmd._build_check_families(
            context=_build_doctor_context(state),
            actions=post_actions,
            hook_map={},
            agent_index={},
            fix=False,
        )
        checks_after_by_id = {check.check_id: check for check in checks_after}
        startup_codes_after = {
            finding.code
            for finding in checks_after_by_id["startup_blocking_lineage_consistency"].findings
        }
        assert "metadata-work-branch-conflict" not in startup_codes_after
        assert "metadata-worktree-path-conflict" not in startup_codes_after
        assert not checks_after_by_id["prefix_migration_drift"].findings
