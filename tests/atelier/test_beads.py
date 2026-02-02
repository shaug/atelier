from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import atelier.beads as beads


def test_ensure_agent_bead_returns_existing() -> None:
    existing = {"id": "atelier-1", "title": "agent"}
    with patch("atelier.beads.find_agent_bead", return_value=existing):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo")
        )
    assert result == existing


def test_ensure_agent_bead_creates_when_missing() -> None:
    def fake_command(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess(
            args=["bd"], returncode=0, stdout="atelier-2\n", stderr=""
        )

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[0] == "show":
            return [{"id": "atelier-2", "title": "agent"}]
        return []

    with (
        patch("atelier.beads.find_agent_bead", return_value=None),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo"), role="worker"
        )

    assert result["id"] == "atelier-2"


def test_claim_epic_updates_assignee_and_status() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": None}
    updated = {"id": "atelier-9", "labels": ["at:hooked"], "assignee": "agent"}

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args and args[0] == "show":
            return [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    called_args = run_command.call_args.args[0]
    assert "update" in called_args
    assert "--assignee" in called_args
    assert "--status" in called_args
    assert "hooked" in called_args


def test_set_agent_hook_updates_description() -> None:
    issue = {"id": "atelier-agent", "description": "role: worker\n"}
    captured: dict[str, str] = {}

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        return [issue]

    def fake_update(
        issue_id: str, description: str, *, beads_root: Path, cwd: Path
    ) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.set_agent_hook(
            "atelier-agent",
            "atelier-epic",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-agent"
    assert "hook_bead: atelier-epic" in captured["description"]


def test_create_message_bead_renders_frontmatter() -> None:
    with (
        patch("atelier.beads.messages.render_message", return_value="body"),
        patch("atelier.beads._create_issue_with_body", return_value="atelier-55"),
        patch(
            "atelier.beads.run_bd_json",
            return_value=[{"id": "atelier-55", "title": "Hello"}],
        ),
    ):
        result = beads.create_message_bead(
            subject="Hello",
            body="Hi",
            metadata={"from": "alice"},
            assignee="bob",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )
    assert result["id"] == "atelier-55"


def test_list_inbox_messages_filters_unread() -> None:
    with patch(
        "atelier.beads.run_bd_json", return_value=[{"id": "atelier-77"}]
    ) as run_json:
        result = beads.list_inbox_messages(
            "alice", beads_root=Path("/beads"), cwd=Path("/repo")
        )
    assert result
    called_args = run_json.call_args.args[0]
    assert "--label" in called_args
    assert "at:unread" in called_args


def test_mark_message_read_updates_labels() -> None:
    with patch("atelier.beads.run_bd_command") as run_command:
        beads.mark_message_read(
            "atelier-88", beads_root=Path("/beads"), cwd=Path("/repo")
        )
    called_args = run_command.call_args.args[0]
    assert "update" in called_args
    assert "--remove-label" in called_args


def test_update_changeset_review_updates_description() -> None:
    issue = {"id": "atelier-99", "description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        return [issue]

    def fake_update(
        issue_id: str, description: str, *, beads_root: Path, cwd: Path
    ) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_changeset_review(
            "atelier-99",
            beads.changesets.ReviewMetadata(pr_state="review"),
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-99"
    assert "pr_state: review" in captured["description"]


def test_update_worktree_path_writes_description() -> None:
    issue = {"id": "epic-1", "description": "workspace.root_branch: main\n"}
    captured: dict[str, str] = {}

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        return [issue]

    def fake_update(
        issue_id: str, description: str, *, beads_root: Path, cwd: Path
    ) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_worktree_path(
            "epic-1", "worktrees/epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert captured["id"] == "epic-1"
    assert "worktree_path: worktrees/epic-1" in captured["description"]


def test_parse_external_tickets_reads_json() -> None:
    description = (
        'external_tickets: [{"provider":"github","id":"123","url":"u"}]\nscope: demo\n'
    )
    tickets = beads.parse_external_tickets(description)
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.provider == "github"
    assert ticket.ticket_id == "123"
    assert ticket.url == "u"


def test_update_external_tickets_updates_labels() -> None:
    issue = {"id": "issue-1", "description": "scope: demo\n", "labels": ["ext:github"]}
    captured: dict[str, object] = {"commands": []}

    def fake_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        return [issue]

    def fake_command(args: list[str], *, beads_root: Path, cwd: Path) -> None:
        captured["commands"].append(args)

    def fake_update(
        issue_id: str, description: str, *, beads_root: Path, cwd: Path
    ) -> None:
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_external_tickets(
            "issue-1",
            [beads.ExternalTicketRef(provider="jira", ticket_id="J-1")],
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert "external_tickets:" in str(captured.get("description", ""))
    update_calls = [cmd for cmd in captured["commands"] if cmd and cmd[0] == "update"]
    assert update_calls
    combined = " ".join(update_calls[0])
    assert "--add-label" in combined
    assert "ext:jira" in combined
    assert "--remove-label" in combined
    assert "ext:github" in combined
