from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

import atelier.lib.beads as beads_lib
from atelier import messages, planner_overview, planner_startup_check
from atelier.lib.beads import (
    BeadsCommandRequest,
    BeadsCommandResult,
    ShowIssueRequest,
    SubprocessBeadsClient,
)
from atelier.store import build_atelier_store
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "planner-store-migration-contract.md"
SKILLS_DIR = REPO_ROOT / "src" / "atelier" / "skills"
BUILDER = IssueFixtureBuilder()
_BACKENDS = ("in-memory", "subprocess")


class _InMemorySubprocessTransport:
    """Drive ``SubprocessBeadsClient`` from the in-memory command backend."""

    def __init__(self, backend: InMemoryBeadsBackend) -> None:
        self._backend = backend

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        completed = self._backend.run(request.argv, cwd=request.cwd, env=request.env)
        return BeadsCommandResult(
            argv=request.argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _seed_issues() -> tuple[dict[str, object], ...]:
    return (
        BUILDER.issue(
            "at-epic",
            title="Planner migration epic",
            issue_type="epic",
            status="open",
            labels=("at:epic", "atelier"),
            description="workspace.root_branch: root/planner\n",
        ),
        BUILDER.issue(
            "at-epic.1",
            title="Planner execution slice",
            parent="at-epic",
            status="open",
            labels=("atelier",),
            description=(
                "changeset.root_branch: root/planner\n"
                "changeset.parent_branch: main\n"
                "changeset.work_branch: root/planner-at-epic.1\n"
            ),
        ),
        BUILDER.issue(
            "at-epic.2",
            title="Deferred planner follow-up",
            parent="at-epic",
            status="deferred",
            labels=("atelier",),
        ),
        BUILDER.issue(
            "msg-inbox",
            title="NEEDS-DECISION: choose planner path",
            issue_type="message",
            labels=("at:message", "at:unread"),
            description=messages.render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "thread": "at-epic.1",
                    "thread_kind": "changeset",
                    "audience": ["planner"],
                    "kind": "needs-decision",
                    "blocking": True,
                },
                "Choose the planner migration path.",
            ),
        ),
        BUILDER.issue(
            "msg-queue",
            title="Queued planner follow-up",
            issue_type="message",
            labels=("at:message", "at:unread"),
            description=messages.render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "thread": "at-epic.1",
                    "thread_kind": "changeset",
                    "audience": ["planner"],
                    "queue": "planner",
                    "kind": "instruction",
                },
                "Queue this planner follow-up.",
            ),
        ),
    )


def _backend_client(backend: str):
    issues = _seed_issues()
    if backend == "in-memory":
        client, _ = build_in_memory_beads_client(issues=issues)
        return client
    if backend == "subprocess":
        command_backend = InMemoryBeadsBackend(seeded_issues=issues)
        return SubprocessBeadsClient(transport=_InMemorySubprocessTransport(command_backend))
    raise AssertionError(f"unexpected backend: {backend}")


def _store_for_backend(backend: str):
    client = _backend_client(backend)
    return client, build_atelier_store(beads=client)


def _load_skill_script(*parts: str):
    script_path = REPO_ROOT / "src" / "atelier" / "skills" / parts[0] / "scripts" / parts[1]
    module_name = "test_" + "_".join(part.replace("-", "_").replace(".", "_") for part in parts)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("backend", _BACKENDS)
def test_planner_startup_and_discovery_have_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    _client, store = _store_for_backend(backend)
    monkeypatch.setattr(planner_startup_check, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(planner_overview, "_build_store", lambda **_kwargs: store)

    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    epics = helper.list_epics()
    rendered_epics = planner_overview.render_epics(epics, show_drafts=True)
    parity = helper.epic_discovery_parity_report()
    snapshot = {
        "inbox": tuple(
            (item["id"], item["title"])
            for item in sorted(
                helper.list_inbox_messages("atelier/planner/codex/p200"),
                key=lambda item: str(item["id"]),
            )
        ),
        "queue": tuple(
            (item["id"], item["queue"], item["title"], item["claimed_by"])
            for item in sorted(
                helper.list_queue_messages(queue="planner", unclaimed_only=False),
                key=lambda item: str(item["id"]),
            )
        ),
        "epics": tuple((item["id"], item["status"], item["title"]) for item in epics),
        "changesets": tuple(
            (item["id"], item["status"], item["title"])
            for item in sorted(
                helper.list_descendant_changesets("at-epic"),
                key=lambda item: str(item["id"]),
            )
        ),
        "parity": parity.model_dump(mode="json"),
        "rendered_epics": rendered_epics,
    }

    assert snapshot == {
        "inbox": (
            (
                "msg-inbox",
                "NEEDS-DECISION: choose planner path "
                "(changeset=at-epic.1; kind=needs-decision; audience=planner) | "
                "Choose the planner migration path.",
            ),
        ),
        "queue": (("msg-queue", "planner", "Queued planner follow-up", None),),
        "epics": (("at-epic", "open", "Planner migration epic"),),
        "changesets": (
            ("at-epic.1", "open", "Planner execution slice"),
            ("at-epic.2", "deferred", "Deferred planner follow-up"),
        ),
        "parity": {
            "active_top_level_work_count": 1,
            "indexed_active_epic_count": 1,
            "missing_executable_identity": [],
            "missing_from_index": [],
        },
        "rendered_epics": "\n".join(
            [
                "Epics by state:",
                "",
                "Open epics:",
                "- at-epic [open] Planner migration epic",
                "  root: root/planner | assignee: unassigned",
            ]
        ),
    }


@pytest.mark.parametrize("backend", _BACKENDS)
def test_planner_authoring_and_message_flows_have_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    tmp_path: Path,
) -> None:
    client, store = _store_for_backend(backend)
    context = type(
        "Context",
        (),
        {
            "project_dir": tmp_path / "repo",
            "beads_root": tmp_path / ".beads",
        },
    )()
    context.project_dir.mkdir(parents=True, exist_ok=True)
    context.beads_root.mkdir(parents=True, exist_ok=True)

    create_epic = _load_skill_script("plan-create-epic", "create_epic.py")
    create_changeset = _load_skill_script("plan-changesets", "create_changeset.py")
    mail_inbox = _load_skill_script("mail-inbox", "list_inbox.py")
    mail_send = _load_skill_script("mail-send", "send_message.py")
    mail_queue_claim = _load_skill_script("mail-queue-claim", "claim_message.py")
    mail_mark_read = _load_skill_script("mail-mark-read", "mark_read.py")

    monkeypatch.setattr(create_epic, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        create_epic.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        create_epic.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: create_epic.auto_export.AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=None,
            message="auto-export disabled for test",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "Planner contract proof epic",
            "--scope",
            "Prove planner store migration parity.",
            "--acceptance",
            "Planner startup and authoring depend on atelier.store.",
            "--no-export",
        ],
    )
    create_epic.main()

    monkeypatch.setattr(create_changeset, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(beads_lib, "SubprocessBeadsClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        create_changeset.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        create_changeset.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: create_changeset.auto_export.AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=None,
            message="auto-export disabled for test",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_changeset.py",
            "--epic-id",
            "at-1",
            "--title",
            "Planner contract proof changeset",
            "--acceptance",
            "Planner message and authoring flows stay store-backed.",
            "--description",
            "Keep the proof deterministic.",
            "--no-export",
        ],
    )
    create_changeset.main()

    monkeypatch.setattr(mail_inbox, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(mail_send, "SubprocessBeadsClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        mail_send, "build_atelier_store", lambda *, beads: build_atelier_store(beads=beads)
    )
    monkeypatch.setattr(mail_queue_claim, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(mail_mark_read, "_build_store", lambda **_kwargs: store)

    dispatched = mail_send.dispatch_message(
        subject="NEEDS-DECISION: confirm planner contract",
        body="Confirm the planner contract proof.",
        to="atelier/planner/codex/p200",
        from_agent="atelier/worker/codex/p100",
        thread="at-epic.1",
        reply_to=None,
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    inbox_before_read = tuple(
        item["id"]
        for item in mail_inbox.list_inbox_messages(
            agent_id="atelier/planner/codex/p200",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
    )
    claimed = mail_queue_claim.claim_message(
        message_id="msg-queue",
        claimed_by="atelier/planner/codex/p200",
        queue="planner",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    marked_read = mail_mark_read.mark_message_read(
        message_id="msg-queue",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    inbox_after_read = tuple(
        item["id"]
        for item in mail_inbox.list_inbox_messages(
            agent_id="atelier/planner/codex/p200",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
    )
    dispatched_issue = asyncio.run(client.show(ShowIssueRequest(issue_id=dispatched.issue_id)))
    created_epic = asyncio.run(store.get_epic("at-1"))
    created_changeset = asyncio.run(store.get_changeset("at-2"))
    snapshot = {
        "created_epic": (
            created_epic.id,
            created_epic.lifecycle.value,
            created_epic.labels,
        ),
        "created_changeset": (
            created_changeset.id,
            created_changeset.epic_id,
            created_changeset.lifecycle.value,
            created_changeset.labels,
        ),
        "dispatched": (
            dispatched.decision,
            dispatched.issue_id,
            dispatched.recipient,
            dispatched_issue.assignee,
        ),
        "inbox_before_read": inbox_before_read,
        "claimed": (
            claimed["id"],
            claimed["queue"],
            claimed["claimed_by"],
            claimed["thread_id"],
            claimed["thread_kind"],
        ),
        "marked_read": (
            marked_read["id"],
            marked_read["queue"],
            marked_read["thread_id"],
            marked_read["thread_kind"],
            marked_read["read"],
        ),
        "inbox_after_read": inbox_after_read,
    }

    assert snapshot == {
        "created_epic": ("at-1", "deferred", ("at:epic", "ext:no-export")),
        "created_changeset": ("at-2", "at-1", "deferred", ("ext:no-export",)),
        "dispatched": (
            "delivered",
            "at-3",
            "atelier/planner/codex/p200",
            "atelier/planner/codex/p200",
        ),
        "inbox_before_read": ("at-3", "msg-inbox", "msg-queue"),
        "claimed": (
            "msg-queue",
            "planner",
            "atelier/planner/codex/p200",
            "at-epic.1",
            "changeset",
        ),
        "marked_read": (
            "msg-queue",
            "planner",
            "at-epic.1",
            "changeset",
            True,
        ),
        "inbox_after_read": ("at-3", "msg-inbox"),
    }


def test_planner_store_migration_docs_publish_boundary_and_deferred_gaps() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    startup_skill = (SKILLS_DIR / "planner-startup-check" / "SKILL.md").read_text(encoding="utf-8")
    create_epic_skill = (SKILLS_DIR / "plan-create-epic" / "SKILL.md").read_text(encoding="utf-8")
    create_changeset_skill = (SKILLS_DIR / "plan-changesets" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    mail_send_skill = (SKILLS_DIR / "mail-send" / "SKILL.md").read_text(encoding="utf-8")
    promote_skill = (SKILLS_DIR / "plan-promote-epic" / "SKILL.md").read_text(encoding="utf-8")

    assert "Planner Store Migration Contract" in doc
    assert "Proven Planner Boundary" in doc
    assert "Planner Compatibility Seams" in doc
    assert "`mail-send`" in doc
    assert "assignee recipient hint" in doc
    assert "plan-promote-epic" in doc
    assert "preview still expands raw issue detail" in doc
    assert "[Worker Store Migration Contract]" in doc
    assert "publish and integration orchestration migrations onto `atelier.store`" in doc

    assert "[Planner Store Migration Contract]" in startup_skill
    assert "adapter-local startup compatibility projections" in startup_skill
    assert "`atelier.store.CreateEpicRequest`" in create_epic_skill
    assert "`atelier.store.CreateChangesetRequest`" in create_changeset_skill
    assert "`atelier.store.CreateMessageRequest`" in mail_send_skill
    assert "compatibility-only metadata" in mail_send_skill
    assert "[Planner Store Migration Contract]" in promote_skill
    assert "preview still" in promote_skill
    assert "raw issue detail" in promote_skill
