import tempfile
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
        "external_import",
        "external_sync",
        "external_close",
        "beads",
        "claim_epic",
        "epic_claim",
        "epic_list",
        "release_epic",
        "hook_status",
        "heartbeat",
        "work_done",
        "mail_send",
        "mail_inbox",
        "mail_mark_read",
        "mail_queue_claim",
        "mail_channel_post",
        "changeset_review",
        "changeset_signals",
        "pr_draft",
        "startup_contract",
        "plan_create_epic",
        "plan_split_tasks",
        "plan_changesets",
        "plan_changeset_guardrails",
    }.issubset(names)


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
            "external_import",
            "external_sync",
            "external_close",
            "beads",
            "claim_epic",
            "epic_claim",
            "epic_list",
            "release_epic",
            "hook_status",
            "heartbeat",
            "work_done",
            "mail_send",
            "mail_inbox",
            "mail_mark_read",
            "mail_queue_claim",
            "mail_channel_post",
            "changeset_review",
            "changeset_signals",
            "pr_draft",
            "startup_contract",
            "plan_create_epic",
            "plan_split_tasks",
            "plan_changesets",
            "plan_changeset_guardrails",
        ):
            assert (workspace_dir / "skills" / name / "SKILL.md").exists()


def test_publish_skill_mentions_pr_draft_and_github_prs() -> None:
    skill = skills.load_packaged_skills()["publish"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "pr_draft" in text
    assert "github-prs" in text


def test_tickets_skill_mentions_import_export_and_sync() -> None:
    skill = skills.load_packaged_skills()["tickets"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "import" in text
    assert "export" in text
    assert "sync_state" in text
    assert "external_import" in text
    assert "external_sync" in text


def test_github_issues_skill_mentions_list_script() -> None:
    skill = skills.load_packaged_skills()["github-issues"]
    text = skill.files["SKILL.md"].decode("utf-8")
    assert "list_issues.py" in text
