import shutil
import tempfile
from importlib import resources
from pathlib import Path

import atelier.skills as skills


def test_packaged_skills_include_core_set() -> None:
    names = set(skills.list_packaged_skills())
    assert {
        "publish",
        "github",
        "github-issues",
        "github-prs",
        "tickets",
        "external-import",
        "external-sync",
        "external-close",
        "beads",
        "import-legacy-tickets",
        "claim-epic",
        "epic-claim",
        "epic-list",
        "release-epic",
        "hook-status",
        "heartbeat",
        "work-done",
        "mail-send",
        "mail-inbox",
        "mail-mark-read",
        "mail-queue-claim",
        "mail-channel-post",
        "changeset-review",
        "changeset-signals",
        "pr-draft",
        "startup-contract",
        "plan-create-epic",
        "plan-split-tasks",
        "plan-changesets",
        "plan-changeset-guardrails",
        "plan-promote-epic",
        "planner-startup-check",
    }.issubset(names)
    assert all("_" not in name for name in names)


def test_packaged_skills_tree_has_no_snake_case_directories() -> None:
    root = resources.files("atelier").joinpath("skills")
    dir_names = sorted(entry.name for entry in root.iterdir() if entry.is_dir())
    assert all("_" not in name for name in dir_names)


def test_install_workspace_skills_writes_skill_docs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace_dir = Path(tmp)
        metadata = skills.install_workspace_skills(workspace_dir)
        assert metadata
        for name in (
            "publish",
            "github",
            "github-issues",
            "github-prs",
            "tickets",
            "external-import",
            "external-sync",
            "external-close",
            "beads",
            "import-legacy-tickets",
            "claim-epic",
            "epic-claim",
            "epic-list",
            "release-epic",
            "hook-status",
            "heartbeat",
            "work-done",
            "mail-send",
            "mail-inbox",
            "mail-mark-read",
            "mail-queue-claim",
            "mail-channel-post",
            "changeset-review",
            "changeset-signals",
            "pr-draft",
            "startup-contract",
            "plan-create-epic",
            "plan-split-tasks",
            "plan-changesets",
            "plan-changeset-guardrails",
            "plan-promote-epic",
            "planner-startup-check",
        ):
            assert (workspace_dir / "skills" / name / "SKILL.md").exists()


def test_packaged_planning_skills_include_scripts() -> None:
    definitions = skills.load_packaged_skills()
    assert "scripts/create_changeset.py" in definitions["plan-changesets"].files
    assert "scripts/create_epic.py" in definitions["plan-create-epic"].files
    assert "scripts/refresh_overview.py" in definitions["planner-startup-check"].files
    assert "scripts/import_legacy_tickets.py" in definitions["import-legacy-tickets"].files
    assert "scripts/send_message.py" in definitions["mail-send"].files


def test_work_done_skill_references_close_epic_script() -> None:
    skill = skills.load_packaged_skills()["work-done"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "scripts/close_epic.py" in text
    assert "--direct-close" in text


def test_publish_skill_mentions_pr_draft_and_github_prs() -> None:
    skill = skills.load_packaged_skills()["publish"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "pr-draft" in text
    assert "github-prs" in text


def test_tickets_skill_mentions_import_export_and_sync() -> None:
    skill = skills.load_packaged_skills()["tickets"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "import" in text
    assert "export" in text
    assert "sync_state" in text
    assert "external-import" in text
    assert "external-sync" in text


def test_github_issues_skill_mentions_list_script() -> None:
    skill = skills.load_packaged_skills()["github-issues"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "list_issues.py" in text


def test_ensure_project_skills_installs_if_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        skills_dir = skills.ensure_project_skills(project_dir)
        assert skills_dir == project_dir / "skills"
        assert (skills_dir / "planner-startup-check" / "SKILL.md").exists()


def test_sync_project_skills_installs_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        result = skills.sync_project_skills(project_dir)
        assert result.action == "installed"
        assert result.skills_dir == project_dir / "skills"
        assert (project_dir / "skills" / "planner-startup-check" / "SKILL.md").exists()


def test_sync_project_skills_updates_when_packaged_skill_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        skills.install_workspace_skills(project_dir)
        stale_skill = project_dir / "skills" / "planner-startup-check"
        assert stale_skill.exists()
        shutil.rmtree(stale_skill)

        result = skills.sync_project_skills(project_dir)
        assert result.action == "updated"
        assert stale_skill.exists()


def test_sync_project_skills_applies_upgrade_with_yes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        skills.install_workspace_skills(project_dir)
        stale_skill = project_dir / "skills" / "planner-startup-check"
        shutil.rmtree(stale_skill)

        result = skills.sync_project_skills(project_dir, yes=True)
        assert result.action == "updated"
        assert (project_dir / "skills" / "planner-startup-check" / "SKILL.md").exists()


def test_sync_project_skills_overwrites_when_locally_modified() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        skills.install_workspace_skills(project_dir)
        skill_doc = project_dir / "skills" / "publish" / "SKILL.md"
        skill_doc.write_text(skill_doc.read_text(encoding="utf-8") + "\nlocal\n")

        result = skills.sync_project_skills(project_dir)
        assert result.action == "updated"
        assert "local" not in skill_doc.read_text(encoding="utf-8")


def test_sync_project_skills_overwrites_local_changes_with_yes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        skills.install_workspace_skills(project_dir)
        skill_doc = project_dir / "skills" / "publish" / "SKILL.md"
        original = skill_doc.read_text(encoding="utf-8")
        skill_doc.write_text(original + "\nlocal\n")

        result = skills.sync_project_skills(project_dir, yes=True)
        assert result.action == "updated"
        assert skill_doc.read_text(encoding="utf-8") == original


def test_packaged_skill_docs_include_yaml_frontmatter() -> None:
    definitions = skills.load_packaged_skills()
    for name, definition in definitions.items():
        text = definition.files["SKILL.md"].decode("utf-8").lstrip()
        assert text.startswith("---\n"), f"{name} SKILL.md missing YAML frontmatter"


def test_plan_changesets_skill_requires_rationale_for_one_child_split() -> None:
    skill = skills.load_packaged_skills()["plan-changesets"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "one child changeset" in text
    assert "decomposition rationale" in text
    assert "Default new changesets to `status=deferred`" in text
    assert "immediately prompt the operator" in text
    assert "safe default" in text


def test_plan_changeset_guardrails_skill_mentions_checker_script() -> None:
    skill = skills.load_packaged_skills()["plan-changeset-guardrails"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "scripts/check_guardrails.py" in text
    assert "one child changeset" in text
    assert "decomposition rationale" in text


def test_plan_promote_epic_skill_requires_one_child_rationale() -> None:
    skill = skills.load_packaged_skills()["plan-promote-epic"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "exactly one child changeset" in text
    assert "decomposition rationale" in text


def test_plan_create_epic_skill_captures_drafts_without_approval() -> None:
    skill = skills.load_packaged_skills()["plan-create-epic"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "capture it as a deferred epic immediately" in text
    assert "not request approval to create or edit deferred beads." in text


def test_planner_startup_check_skill_captures_drafts_without_approval() -> None:
    skill = skills.load_packaged_skills()["planner-startup-check"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "Create or update deferred beads immediately" in text
    assert "Do not wait for approval to capture deferred work." in text
    assert "new changeset under an active epic" in text
    assert "readiness outcome in notes/status" in text


def test_workspace_skill_state_accepts_legacy_underscore_metadata_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        canonical = skills.install_workspace_skills(project_dir)
        legacy = {name.replace("-", "_"): payload for name, payload in canonical.items()}

        state = skills.workspace_skill_state(project_dir, legacy)

        assert state.needs_install is False
        assert state.needs_metadata is False
