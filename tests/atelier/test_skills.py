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
        "beads",
        "claim_epic",
        "release_epic",
        "hook_status",
        "heartbeat",
        "work_done",
        "mail_send",
        "mail_inbox",
        "mail_mark_read",
        "changeset_review",
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
            "beads",
            "claim_epic",
            "release_epic",
            "hook_status",
            "heartbeat",
            "work_done",
            "mail_send",
            "mail_inbox",
            "mail_mark_read",
            "changeset_review",
        ):
            assert (workspace_dir / "skills" / name / "SKILL.md").exists()
