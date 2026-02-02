from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.mail as mail_cmd
from atelier.agent_home import AgentHome
from atelier.config import ProjectConfig


def _fake_project_payload() -> ProjectConfig:
    return ProjectConfig()


def test_mail_send_creates_message() -> None:
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    with (
        patch(
            "atelier.commands.mail.resolve_current_project_with_repo_root",
            return_value=(Path("/project"), _fake_project_payload(), "/repo", Path("/repo")),
        ),
        patch(
            "atelier.commands.mail.config.resolve_project_data_dir",
            return_value=Path("/project"),
        ),
        patch(
            "atelier.commands.mail.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.mail.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch(
            "atelier.commands.mail.beads.create_message_bead",
            return_value={"id": "atelier-1"},
        ) as create_message,
        patch("atelier.commands.mail.say"),
    ):
        mail_cmd.send_mail(
            SimpleNamespace(
                to="atelier/worker/alice",
                subject="Hello",
                body="Hi",
                body_file=None,
                sender=None,
                thread=None,
                reply_to=None,
            )
        )

    assert create_message.called


def test_mail_inbox_lists_messages() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/alice",
        role="worker",
        path=Path("/project/agents/worker"),
    )
    with (
        patch(
            "atelier.commands.mail.resolve_current_project_with_repo_root",
            return_value=(Path("/project"), _fake_project_payload(), "/repo", Path("/repo")),
        ),
        patch(
            "atelier.commands.mail.config.resolve_project_data_dir",
            return_value=Path("/project"),
        ),
        patch(
            "atelier.commands.mail.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.mail.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch(
            "atelier.commands.mail.beads.list_inbox_messages",
            return_value=[{"id": "atelier-2", "title": "Ping"}],
        ) as list_messages,
        patch("atelier.commands.mail.say"),
    ):
        mail_cmd.inbox(SimpleNamespace(agent=None, all=False))

    assert list_messages.called


def test_mail_mark_read_updates_message() -> None:
    with (
        patch(
            "atelier.commands.mail.resolve_current_project_with_repo_root",
            return_value=(Path("/project"), _fake_project_payload(), "/repo", Path("/repo")),
        ),
        patch(
            "atelier.commands.mail.config.resolve_project_data_dir",
            return_value=Path("/project"),
        ),
        patch(
            "atelier.commands.mail.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.mail.beads.mark_message_read") as mark_read,
        patch("atelier.commands.mail.say"),
    ):
        mail_cmd.mark_read(SimpleNamespace(message_id="atelier-3"))

    assert mark_read.called
