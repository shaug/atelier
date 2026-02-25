import json
import sqlite3
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import atelier.beads as beads


def test_run_bd_issue_records_validates_issues() -> None:
    with patch(
        "atelier.beads.run_bd_json",
        return_value=[{"id": "at-1", "labels": ["at:changeset"], "status": "open"}],
    ):
        records = beads.run_bd_issue_records(
            ["list"], beads_root=Path("/beads"), cwd=Path("/repo"), source="test"
        )
    assert len(records) == 1
    assert records[0].issue.id == "at-1"
    assert records[0].raw["id"] == "at-1"


def test_run_bd_issue_records_rejects_invalid_payload() -> None:
    with patch(
        "atelier.beads.run_bd_json",
        return_value=[{"labels": ["at:changeset"], "status": "open"}],
    ):
        with pytest.raises(ValueError, match="invalid beads issue payload"):
            beads.run_bd_issue_records(
                ["list"], beads_root=Path("/beads"), cwd=Path("/repo"), source="test"
            )


def test_ensure_agent_bead_returns_existing() -> None:
    existing = {"id": "atelier-1", "title": "agent"}
    with patch("atelier.beads.find_agent_bead", return_value=existing):
        result = beads.ensure_agent_bead("agent", beads_root=Path("/beads"), cwd=Path("/repo"))
    assert result == existing


def test_ensure_agent_bead_creates_when_missing() -> None:
    def fake_command(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=["bd"], returncode=0, stdout="atelier-2\n", stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[0] == "show":
            return [{"id": "atelier-2", "title": "agent"}]
        return []

    with (
        patch("atelier.beads.find_agent_bead", return_value=None),
        patch("atelier.beads._agent_issue_type", return_value="task"),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo"), role="worker"
        )

    assert result["id"] == "atelier-2"


def test_ensure_atelier_store_initializes_missing_root() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp) / ".beads"
        with patch("atelier.beads.run_bd_command") as run_command:
            changed = beads.ensure_atelier_store(beads_root=beads_root, cwd=Path("/repo"))

    assert changed is True
    assert run_command.call_args.args[0] == ["init", "--prefix", "at", "--quiet"]


def test_ensure_atelier_store_skips_existing_root() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp) / ".beads"
        beads_root.mkdir(parents=True)
        with patch("atelier.beads.run_bd_command") as run_command:
            changed = beads.ensure_atelier_store(beads_root=beads_root, cwd=Path("/repo"))

    assert changed is False
    run_command.assert_not_called()


def test_prime_addendum_returns_output() -> None:
    with patch(
        "atelier.beads.subprocess.run",
        return_value=CompletedProcess(
            args=["bd", "prime"], returncode=0, stdout="# Addendum\n", stderr=""
        ),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value == "# Addendum"


def test_prime_addendum_returns_none_on_error() -> None:
    with patch(
        "atelier.beads.subprocess.run",
        return_value=CompletedProcess(args=["bd", "prime"], returncode=1, stdout="", stderr="boom"),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value is None


def test_ensure_issue_prefix_noop_when_already_expected() -> None:
    with (
        patch("atelier.beads._current_issue_prefix", return_value="at"),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is False
    run_command.assert_not_called()


def test_ensure_issue_prefix_updates_when_mismatched() -> None:
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        calls.append(args)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads._current_issue_prefix", return_value="atelier"),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is True
    assert calls[0] == ["config", "set", "issue_prefix", "at"]
    assert calls[1] == ["rename-prefix", "at-", "--repair"]


def test_claim_epic_updates_assignee_and_status() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": None}
    updated = {"id": "atelier-9", "labels": ["at:hooked"], "assignee": "agent"}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
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


def test_claim_epic_allows_expected_takeover() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": "agent-old"}
    updated = {"id": "atelier-9", "labels": ["at:hooked"], "assignee": "agent-new"}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args and args[0] == "show":
            return [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent-new",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            allow_takeover_from="agent-old",
        )

    called_args = run_command.call_args.args[0]
    assert "--assignee" in called_args
    assert "agent-new" in called_args


def test_claim_epic_blocks_planner_owned_executable_work() -> None:
    issue = {
        "id": "atelier-9",
        "labels": ["at:epic", "at:changeset", "at:ready"],
        "assignee": "atelier/planner/codex/p111",
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "atelier/worker/codex/p222",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
    assert "planner agents cannot own executable work" in str(die_fn.call_args.args[0])


def test_claim_epic_rejects_planner_claimant_for_executable_work() -> None:
    issue = {
        "id": "atelier-9",
        "labels": ["at:epic", "at:ready"],
        "assignee": None,
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "atelier/planner/codex/p111",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
    run_command.assert_not_called()
    assert "planner agents cannot claim executable work" in str(die_fn.call_args.args[0])


def test_claim_epic_backfills_epic_label_for_standalone_changeset() -> None:
    issue = {"id": "at-legacy", "labels": ["at:changeset", "at:ready"], "assignee": None}
    updated = {
        "id": "at-legacy",
        "labels": ["at:changeset", "at:epic", "at:hooked", "at:ready"],
        "assignee": "agent",
    }
    show_calls = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        nonlocal show_calls
        if args and args[0] == "show":
            show_calls += 1
            return [issue] if show_calls == 1 else [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "at-legacy",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    called_args = run_command.call_args.args[0]
    assert called_args.count("--add-label") == 2
    assert "at:hooked" in called_args
    assert "at:epic" in called_args


def test_claim_epic_requires_explicit_ready_for_executable_work() -> None:
    issue = {"id": "at-legacy", "labels": ["at:epic"], "assignee": None}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "at-legacy",
                "agent",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert "not marked at:ready" in str(die_fn.call_args.args[0])


def test_claim_epic_rejects_legacy_draft_label() -> None:
    issue = {"id": "at-legacy", "labels": ["at:epic", "at:draft"], "assignee": None}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "at-legacy",
                "agent",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert "legacy at:draft label" in str(die_fn.call_args.args[0])


def test_set_agent_hook_updates_description() -> None:
    issue = {"id": "atelier-agent", "description": "role: worker\n"}
    captured: dict[str, str] = {}
    called: dict[str, list[str]] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        called["args"] = args
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
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
    assert called["args"][:3] == ["slot", "set", "atelier-agent"]


def test_update_changeset_branch_metadata_skips_base_overwrite_by_default() -> None:
    issue = {
        "id": "at-1.1",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/root-at-1.1\n"
            "changeset.root_base: aaa111\n"
            "changeset.parent_base: bbb222\n"
        ),
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads._update_issue_description") as update_desc,
    ):
        result = beads.update_changeset_branch_metadata(
            "at-1.1",
            root_branch="feat/root",
            parent_branch="main",
            work_branch="feat/root-at-1.1",
            root_base="ccc333",
            parent_base="ddd444",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    update_desc.assert_not_called()
    assert result == issue


def test_get_agent_hook_prefers_slot() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        return CompletedProcess(args=args, returncode=0, stdout='{"hook":"epic-1"}\n', stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-1"


def test_get_agent_hook_falls_back_to_description() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        return CompletedProcess(args=args, returncode=1, stdout="", stderr="err")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-2"


def test_get_agent_hook_backfills_slot() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["slot", "show"]:
            return CompletedProcess(args=args, returncode=0, stdout="{}\n", stderr="")
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-2"
    assert any(args[:2] == ["slot", "set"] for args in calls)


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


def test_claim_queue_message_sets_claimed_metadata() -> None:
    description = "---\nqueue: triage\n---\n\nBody\n"
    issue = {"id": "msg-1", "description": description}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.claim_queue_message(
            "msg-1",
            "atelier/worker/agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "msg-1"
    assert "claimed_by: atelier/worker/agent" in captured["description"]
    assert "claimed_at:" in captured["description"]


def test_list_inbox_messages_filters_unread() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[{"id": "atelier-77"}]) as run_json:
        result = beads.list_inbox_messages("alice", beads_root=Path("/beads"), cwd=Path("/repo"))
    assert result
    called_args = run_json.call_args.args[0]
    assert "--label" in called_args
    assert "at:unread" in called_args


def test_list_queue_messages_filters_unread_by_default() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_json.call_args.args[0]
    assert called_args == ["list", "--label", "at:message", "--label", "at:unread"]


def test_list_queue_messages_can_include_read_messages() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"), unread_only=False)
    called_args = run_json.call_args.args[0]
    assert called_args == ["list", "--label", "at:message"]


def test_mark_message_read_updates_labels() -> None:
    with patch("atelier.beads.run_bd_command") as run_command:
        beads.mark_message_read("atelier-88", beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_command.call_args.args[0]
    assert "update" in called_args
    assert "--remove-label" in called_args


def test_list_descendant_changesets_walks_tree() -> None:
    calls: list[str] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        parent = args[2]
        calls.append(parent)
        if parent == "epic-1":
            return [{"id": "epic-1.1"}, {"id": "epic-1.2"}]
        if parent == "epic-1.1":
            return [{"id": "epic-1.1.1"}]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        issues = beads.list_descendant_changesets(
            "epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert [issue["id"] for issue in issues] == ["epic-1.1", "epic-1.2", "epic-1.1.1"]
    assert calls == ["epic-1", "epic-1.1", "epic-1.2", "epic-1.1.1"]


def test_list_child_changesets_uses_changeset_label() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_child_changesets("epic-1", beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_json.call_args.args[0]
    assert called_args == ["list", "--parent", "epic-1", "--label", "at:changeset"]


def test_summarize_changesets_counts_and_ready() -> None:
    changesets = [
        {"labels": ["cs:merged"]},
        {"labels": ["cs:abandoned"]},
        {"labels": ["cs:ready"]},
    ]
    summary = beads.summarize_changesets(changesets, ready=[changesets[2]])
    assert summary.total == 3
    assert summary.ready == 1
    assert summary.merged == 1
    assert summary.abandoned == 1
    assert summary.remaining == 1
    assert summary.ready_to_close is False


def test_epic_changeset_summary_ready_to_close() -> None:
    changesets = {
        "epic-1": [{"id": "epic-1.1", "labels": ["cs:merged"]}],
        "epic-1.1": [{"id": "epic-1.1.1", "labels": ["cs:abandoned"]}],
        "epic-1.1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"]}]
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        summary = beads.epic_changeset_summary(
            "epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert summary.ready_to_close is True


def test_close_epic_if_complete_closes_and_clears_hook() -> None:
    changesets = {
        "epic-1": [{"id": "epic-1.1", "labels": ["cs:merged"]}],
        "epic-1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"]}]
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            confirm=lambda _summary: True,
        )

    assert result is True
    run_command.assert_called_with(
        ["close", "epic-1"], beads_root=Path("/beads"), cwd=Path("/repo")
    )
    clear_hook.assert_called_once()


def test_close_epic_if_complete_respects_confirm() -> None:
    changesets = {
        "epic-1": [{"id": "epic-1.1", "labels": ["cs:merged"]}],
        "epic-1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.clear_agent_hook"),
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            confirm=lambda _summary: False,
        )

    assert result is False
    run_command.assert_not_called()


def test_close_epic_if_complete_closes_standalone_changeset() -> None:
    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "at-irs"]:
            return [
                {
                    "id": "at-irs",
                    "labels": ["at:changeset", "cs:merged"],
                }
            ]
        if args[:2] == ["list", "--parent"]:
            return []
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "at-irs",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result is True
    run_command.assert_called_with(
        ["close", "at-irs"], beads_root=Path("/beads"), cwd=Path("/repo")
    )
    clear_hook.assert_called_once()


def test_update_changeset_review_updates_description() -> None:
    issue = {"id": "atelier-99", "description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
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


def test_update_changeset_review_feedback_cursor_updates_description() -> None:
    issue = {"id": "atelier-99", "description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_changeset_review_feedback_cursor(
            "atelier-99",
            "2026-02-20T12:00:00Z",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-99"
    assert "review.last_feedback_seen_at: 2026-02-20T12:00:00Z" in captured["description"]


def test_update_worktree_path_writes_description() -> None:
    issue = {"id": "epic-1", "description": "workspace.root_branch: main\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
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
    description = 'external_tickets: [{"provider":"GitHub","id":"123","url":"u","relation":"Primary","direction":"import","sync_mode":"pull","state":"In-Progress","raw_state":"In Progress","state_updated_at":"2026-02-08T10:00:00Z","parent_id":"P-1","on_close":"Close","last_synced_at":"2026-02-08T11:00:00Z"}]\nscope: demo\n'
    tickets = beads.parse_external_tickets(description)
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.provider == "github"
    assert ticket.ticket_id == "123"
    assert ticket.url == "u"
    assert ticket.relation == "primary"
    assert ticket.direction == "imported"
    assert ticket.sync_mode == "import"
    assert ticket.state == "in_progress"
    assert ticket.raw_state == "In Progress"
    assert ticket.state_updated_at == "2026-02-08T10:00:00Z"
    assert ticket.parent_id == "P-1"
    assert ticket.on_close == "close"
    assert ticket.last_synced_at == "2026-02-08T11:00:00Z"


def test_update_external_tickets_updates_labels() -> None:
    issue = {"id": "issue-1", "description": "scope: demo\n", "labels": ["ext:github"]}
    captured: dict[str, object] = {"commands": []}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_command(args: list[str], *, beads_root: Path, cwd: Path) -> None:
        captured["commands"].append(args)

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
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


def test_reconcile_closed_issue_exported_github_tickets_closes_and_updates() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "175",
                "url": "https://api.github.com/repos/acme/widgets/issues/175",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    refreshed = beads.ExternalTicketRef(
        provider="github",
        ticket_id="175",
        url="https://github.com/acme/widgets/issues/175",
        state="closed",
        raw_state="completed",
        state_updated_at="2026-02-25T21:00:00Z",
    )
    captured: dict[str, object] = {}

    def fake_update(
        issue_id: str,
        tickets: list[beads.ExternalTicketRef],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object]:
        captured["issue_id"] = issue_id
        captured["tickets"] = tickets
        return {}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.update_external_tickets", side_effect=fake_update),
        patch(
            "atelier.github_issues_provider.GithubIssuesProvider.close_ticket",
            return_value=refreshed,
        ),
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == tuple()
    assert captured["issue_id"] == "at-4kv"
    updated_tickets = captured["tickets"]
    assert isinstance(updated_tickets, list)
    assert updated_tickets[0].state == "closed"
    assert updated_tickets[0].state_updated_at == "2026-02-25T21:00:00Z"
    assert updated_tickets[0].last_synced_at is not None


def test_reconcile_closed_issue_exported_github_tickets_adds_note_on_missing_repo() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "176",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    notes: list[str] = []

    def fake_command(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> None:
        if "--append-notes" in args:
            notes.append(args[-1])

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.update_external_tickets") as update_external,
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert result.needs_decision_notes
    assert any("missing repo slug" in note for note in result.needs_decision_notes)
    assert any(note.startswith("external_close_pending:") for note in notes)
    update_external.assert_not_called()


def test_reconcile_closed_issue_exported_github_tickets_skips_policy_opt_outs() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "177",
                "url": "https://github.com/acme/widgets/issues/177",
                "relation": "context",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
            },
            {
                "provider": "github",
                "id": "178",
                "url": "https://github.com/acme/widgets/issues/178",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
                "on_close": "none",
            },
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.update_external_tickets") as update_external,
        patch("atelier.github_issues_provider.GithubIssuesProvider.close_ticket") as close_ticket,
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 2
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert result.needs_decision_notes == tuple()
    close_ticket.assert_not_called()
    update_external.assert_not_called()


def test_merge_description_preserving_metadata_keeps_external_tickets() -> None:
    existing = (
        'scope: old\nexternal_tickets: [{"provider":"github","id":"174","direction":"export"}]\n'
    )
    next_description = "Intent\nupdated details\n"

    merged = beads.merge_description_preserving_metadata(existing, next_description)

    assert "Intent" in merged
    assert "external_tickets:" in merged
    assert '"id":"174"' in merged


def test_close_epic_if_complete_reconciles_exported_github_tickets() -> None:
    issue = {"id": "at-4kv", "labels": ["at:epic"], "status": "open"}
    summary = beads.ChangesetSummary(total=1, ready=0, merged=1, abandoned=0, remaining=0)

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.epic_changeset_summary", return_value=summary),
        patch("atelier.beads.run_bd_command") as run_bd_command,
        patch("atelier.beads.reconcile_closed_issue_exported_github_tickets") as reconcile_external,
    ):
        closed = beads.close_epic_if_complete(
            "at-4kv",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert closed is True
    run_bd_command.assert_called_once_with(
        ["close", "at-4kv"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    reconcile_external.assert_called_once_with(
        "at-4kv",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_list_external_ticket_metadata_gaps_detects_missing_field() -> None:
    issue = {
        "id": "at-73j",
        "labels": ["at:epic", "ext:github"],
        "description": "Intent\nno metadata yet\n",
    }
    with patch("atelier.beads.run_bd_json", return_value=[issue]):
        gaps = beads.list_external_ticket_metadata_gaps(
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert len(gaps) == 1
    assert gaps[0].issue_id == "at-73j"
    assert gaps[0].providers == ("github",)


def _seed_events_db(
    db_path: Path, *, issue_id: str, old_description: str, new_description: str
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO events (issue_id, event_type, actor, old_value, new_value)
            VALUES (?, 'updated', 'test-agent', ?, ?)
            """,
            (
                issue_id,
                json.dumps({"description": old_description}),
                json.dumps({"description": new_description}),
            ),
        )
        connection.commit()


def test_recover_external_tickets_from_history_returns_latest_recorded_metadata() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp)
        db_path = beads_root / "beads.db"
        _seed_events_db(
            db_path,
            issue_id="at-73j",
            old_description=(
                "scope: old\n"
                "external_tickets: "
                '[{"provider":"github","id":"174","direction":"export"}]\n'
            ),
            new_description="scope: rewritten\n",
        )
        tickets = beads.recover_external_tickets_from_history("at-73j", beads_root=beads_root)

    assert len(tickets) == 1
    assert tickets[0].provider == "github"
    assert tickets[0].ticket_id == "174"


def test_repair_external_ticket_metadata_from_history_recovers_and_updates() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp)
        db_path = beads_root / "beads.db"
        _seed_events_db(
            db_path,
            issue_id="at-73j",
            old_description=(
                "scope: old\n"
                "external_tickets: "
                '[{"provider":"github","id":"174","direction":"export"}]\n'
            ),
            new_description="scope: rewritten\n",
        )

        issue = {
            "id": "at-73j",
            "labels": ["at:epic", "ext:github"],
            "description": "Intent\nmetadata missing now\n",
        }
        captured: dict[str, object] = {}

        def fake_update(
            issue_id: str,
            tickets: list[beads.ExternalTicketRef],
            *,
            beads_root: Path,
            cwd: Path,
        ) -> dict[str, object]:
            captured["issue_id"] = issue_id
            captured["tickets"] = tickets
            return {}

        with (
            patch("atelier.beads.run_bd_json", return_value=[issue]),
            patch("atelier.beads.update_external_tickets", side_effect=fake_update),
        ):
            results = beads.repair_external_ticket_metadata_from_history(
                beads_root=beads_root,
                cwd=Path("/repo"),
                apply=True,
            )

    assert len(results) == 1
    assert results[0].issue_id == "at-73j"
    assert results[0].recovered is True
    assert results[0].repaired is True
    assert captured["issue_id"] == "at-73j"
    tickets = captured["tickets"]
    assert isinstance(tickets, list)
    assert tickets[0].ticket_id == "174"
