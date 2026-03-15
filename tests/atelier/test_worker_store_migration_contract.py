from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from atelier.lib.beads import (
    BeadsCommandRequest,
    BeadsCommandResult,
    ShowIssueRequest,
    SubprocessBeadsClient,
    SyncBeadsClient,
)
from atelier.messages import render_message
from atelier.store import build_atelier_store
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)
from atelier.worker import changeset_state, finalize, work_startup_runtime
from atelier.worker import store_adapter as worker_store
from atelier.worker.models import FinalizeResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "worker-store-migration-contract.md"
PLANNER_DOC_PATH = REPO_ROOT / "docs" / "planner-store-migration-contract.md"
STORE_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
SKILLS_DIR = REPO_ROOT / "src" / "atelier" / "skills"
BUILDER = IssueFixtureBuilder()
_BACKENDS = ("in-memory", "subprocess")
_BEADS_ROOT = Path("/beads")
_REPO_ROOT = Path("/repo")
_AGENT_ID = "atelier/worker/codex/p100"


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


def _worker_message(
    message_id: str,
    *,
    title: str,
    body: str,
    thread_id: str,
    audience: tuple[str, ...] = ("worker",),
    queue: str | None = None,
    kind: str = "instruction",
    blocking: bool | None = None,
) -> dict[str, object]:
    return BUILDER.issue(
        message_id,
        title=title,
        issue_type="message",
        labels=("at:message", "at:unread"),
        description=render_message(
            {
                "from": "atelier/planner/codex/p200",
                "delivery": "work-threaded",
                "thread": thread_id,
                "thread_kind": "changeset" if "." in thread_id else "epic",
                "audience": list(audience),
                "queue": queue,
                "kind": kind,
                "blocking": blocking,
            },
            body,
        ),
    )


def _startup_seed_issues() -> tuple[dict[str, object], ...]:
    return (
        BUILDER.issue(
            "at-agent",
            title=_AGENT_ID,
            issue_type="agent",
            labels=("at:agent",),
            description=f"agent_id: {_AGENT_ID}\nhook_bead: null\n",
        ),
        BUILDER.issue(
            "at-epic",
            title="Worker migration epic",
            issue_type="epic",
            status="in_progress",
            labels=("at:epic", "at:hooked", "atelier"),
            assignee=_AGENT_ID,
        ),
        BUILDER.issue(
            "at-epic.1",
            title="Worker lifecycle slice",
            parent="at-epic",
            status="open",
            labels=("atelier",),
            dependencies=("at-dep",),
            description=(
                "changeset.root_branch: root/worker\n"
                "changeset.parent_branch: main\n"
                "changeset.work_branch: root/worker-at-epic.1\n"
                "pr_state: pushed\n"
            ),
        ),
        BUILDER.issue(
            "at-dep",
            title="Merged dependency",
            parent="at-epic",
            status="closed",
            labels=("atelier",),
            description="pr_state: merged\n",
        ),
        _worker_message(
            "msg-inbox",
            title="NEEDS-DECISION: review worker contract",
            body="Review the worker migration contract.",
            thread_id="at-epic.1",
            kind="needs-decision",
            blocking=True,
        ),
        _worker_message(
            "msg-terminal",
            title="Ignore closed-thread message",
            body="This message should be filtered because the thread is closed.",
            thread_id="at-dep",
        ),
        _worker_message(
            "msg-queue",
            title="Queued worker follow-up",
            body="Queue this worker follow-up.",
            thread_id="at-epic.1",
            queue="worker",
        ),
    )


def _mutation_seed_issues() -> tuple[dict[str, object], ...]:
    return (
        BUILDER.issue(
            "at-agent",
            title=_AGENT_ID,
            issue_type="agent",
            labels=("at:agent",),
            description=f"agent_id: {_AGENT_ID}\nhook_bead: null\n",
        ),
        BUILDER.issue(
            "at-epic",
            title="Worker finalize epic",
            issue_type="epic",
            status="open",
            labels=("at:epic", "atelier"),
        ),
        BUILDER.issue(
            "at-epic.1",
            title="Finalize worker changeset",
            parent="at-epic",
            status="open",
            labels=("atelier",),
            description=(
                "pr_url: https://example.invalid/pr/41\n"
                "pr_number: 41\n"
                "pr_state: pushed\n"
                "review_owner: reviewer-a\n"
            ),
        ),
        _worker_message(
            "msg-queue",
            title="Queued finalize follow-up",
            body="Queue this finalize follow-up.",
            thread_id="at-epic.1",
            queue="worker",
        ),
    )


def _bind_worker_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: str,
    issues: tuple[dict[str, object], ...],
):
    if backend == "in-memory":
        async_client, _ = build_in_memory_beads_client(issues=issues)
    elif backend == "subprocess":
        command_backend = InMemoryBeadsBackend(seeded_issues=issues)
        async_client = SubprocessBeadsClient(
            transport=_InMemorySubprocessTransport(command_backend)
        )
    else:
        raise AssertionError(f"unexpected backend: {backend}")

    store = build_atelier_store(beads=async_client)
    worker_store.clear_bundle_cache()
    monkeypatch.setattr(
        worker_store,
        "_build_store_bundle",
        lambda **_kwargs: worker_store._StoreBundle(  # pyright: ignore[reportPrivateUsage]
            store=store,
            sync_client=SyncBeadsClient(async_client),
        ),
    )
    return async_client, store


@pytest.mark.parametrize("backend", _BACKENDS)
def test_worker_startup_and_queue_flows_have_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    _client, store = _bind_worker_backend(
        monkeypatch,
        backend=backend,
        issues=_startup_seed_issues(),
    )

    worker_store.set_agent_hook(
        "at-agent",
        "at-epic",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )

    summary = worker_store.epic_changeset_summary(
        "at-epic",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    snapshot = {
        "hooked": work_startup_runtime.resolve_hooked_epic(
            "at-agent",
            _AGENT_ID,
            beads_root=_BEADS_ROOT,
            repo_root=_REPO_ROOT,
        ),
        "inbox": tuple(
            item["id"]
            for item in worker_store.list_inbox_messages(
                _AGENT_ID,
                beads_root=_BEADS_ROOT,
                repo_root=_REPO_ROOT,
            )
        ),
        "queue": tuple(
            (item["id"], item["queue"], item["claimed_by"])
            for item in worker_store.list_queue_messages(
                beads_root=_BEADS_ROOT,
                repo_root=_REPO_ROOT,
                queue="worker",
                unclaimed_only=False,
            )
        ),
        "changesets": tuple(
            (item["id"], item["status"])
            for item in sorted(
                worker_store.list_descendant_changesets(
                    "at-epic",
                    beads_root=_BEADS_ROOT,
                    repo_root=_REPO_ROOT,
                    include_closed=True,
                ),
                key=lambda item: str(item["id"]),
            )
        ),
        "ready": tuple(
            item["id"]
            for item in worker_store.ready_changesets_global(
                beads_root=_BEADS_ROOT,
                repo_root=_REPO_ROOT,
            )
        ),
        "summary": {
            "total": summary.total,
            "ready": summary.ready,
            "remaining": summary.remaining,
        },
        "hook_record": asyncio.run(store.get_agent_bead_hook("at-agent")).model_dump(mode="json"),
    }

    assert snapshot == {
        "hooked": "at-epic",
        "inbox": ("msg-inbox",),
        "queue": (("msg-queue", "worker", None),),
        "changesets": (
            ("at-dep", "closed"),
            ("at-epic.1", "open"),
        ),
        "ready": ("at-epic.1",),
        "summary": {
            "total": 2,
            "ready": 0,
            "remaining": 1,
        },
        "hook_record": {
            "agent_id": _AGENT_ID,
            "epic_id": "at-epic",
        },
    }

    worker_store.clear_bundle_cache()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_worker_inbox_ignores_terminal_changeset_threads_with_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    _client, _store = _bind_worker_backend(
        monkeypatch,
        backend=backend,
        issues=(
            BUILDER.issue(
                "at-agent",
                title=_AGENT_ID,
                issue_type="agent",
                labels=("at:agent",),
                description=f"agent_id: {_AGENT_ID}\nhook_bead: null\n",
            ),
            BUILDER.issue(
                "at-epic",
                title="Worker migration epic",
                issue_type="epic",
                status="open",
                labels=("at:epic", "atelier"),
            ),
            BUILDER.issue(
                "at-epic.1",
                title="Open worker changeset",
                parent="at-epic",
                status="open",
                labels=("atelier",),
                description="pr_state: pushed\n",
            ),
            BUILDER.issue(
                "at-epic.2",
                title="Terminal worker changeset",
                parent="at-epic",
                status="open",
                labels=("atelier",),
                description="pr_state: merged\nchangeset.integrated_sha: abc1234\n",
            ),
            _worker_message(
                "msg-actionable",
                title="Action required on open work",
                body="This unread message should still block startup.",
                thread_id="at-epic.1",
                kind="needs-decision",
                blocking=True,
            ),
            _worker_message(
                "msg-terminal",
                title="Ignore merged-thread message",
                body="This unread message should not block startup anymore.",
                thread_id="at-epic.2",
            ),
        ),
    )

    inbox = worker_store.list_inbox_messages(
        _AGENT_ID,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )

    assert tuple(item["id"] for item in inbox) == ("msg-actionable",)
    worker_store.clear_bundle_cache()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_worker_inbox_keeps_open_changesets_with_stale_closed_pr_state_visible(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    _client, _store = _bind_worker_backend(
        monkeypatch,
        backend=backend,
        issues=(
            BUILDER.issue(
                "at-agent",
                title=_AGENT_ID,
                issue_type="agent",
                labels=("at:agent",),
                description=f"agent_id: {_AGENT_ID}\nhook_bead: null\n",
            ),
            BUILDER.issue(
                "at-epic",
                title="Worker migration epic",
                issue_type="epic",
                status="open",
                labels=("at:epic", "atelier"),
            ),
            BUILDER.issue(
                "at-epic.1",
                title="Open worker changeset with stale closed PR state",
                parent="at-epic",
                status="open",
                labels=("atelier",),
                description="pr_state: closed\n",
            ),
            _worker_message(
                "msg-actionable",
                title="Still block startup on open work",
                body="A stale closed PR marker should not hide this message.",
                thread_id="at-epic.1",
                kind="needs-decision",
                blocking=True,
            ),
        ),
    )

    inbox = worker_store.list_inbox_messages(
        _AGENT_ID,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )

    assert tuple(item["id"] for item in inbox) == ("msg-actionable",)
    worker_store.clear_bundle_cache()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_worker_lifecycle_and_finalize_flows_have_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    _client, store = _bind_worker_backend(
        monkeypatch,
        backend=backend,
        issues=_mutation_seed_issues(),
    )
    monkeypatch.setattr(
        changeset_state.beads,
        "reconcile_closed_issue_exported_github_tickets",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        changeset_state,
        "_load_changeset_issue",
        lambda issue_id, *, beads_root, repo_root: worker_store.show_issue(
            issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
        ),
    )

    claimed = worker_store.claim_epic(
        "at-epic",
        _AGENT_ID,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    worker_store.set_agent_hook(
        "at-agent",
        "at-epic",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    worker_store.append_notes(
        "at-epic.1",
        notes=("worker_contract: parity verified",),
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    worker_store.update_changeset_review(
        "at-epic.1",
        pr_state="merged",
        review_owner="reviewer-b",
        preserve_existing=True,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )

    result = finalize.finalize_terminal_changeset(
        changeset_id="at-epic.1",
        epic_id="at-epic",
        terminal_state="merged",
        integrated_sha="abc1234",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
        mark_changeset_merged=lambda issue_id: changeset_state.mark_changeset_merged(
            issue_id,
            beads_root=_BEADS_ROOT,
            repo_root=_REPO_ROOT,
        ),
        mark_changeset_abandoned=lambda _issue_id: None,
        close_completed_ancestor_container_changesets=lambda _issue_id: [],
        finalize_epic_if_complete=lambda: FinalizeResult(
            continue_running=True,
            reason="changeset_complete",
        ),
    )
    worker_store.claim_queue_message(
        "msg-queue",
        _AGENT_ID,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
        queue="worker",
    )
    worker_store.mark_message_read(
        "msg-queue",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    hooked_before_clear = worker_store.get_agent_hook(
        "at-agent",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    worker_store.clear_agent_hook(
        "at-agent",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
        expected_hook="at-epic",
    )
    changeset_record = asyncio.run(store.get_changeset("at-epic.1"))
    queue_after = worker_store.list_queue_messages(
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
        queue="worker",
        unclaimed_only=False,
        unread_only=False,
    )
    unread_queue_after = worker_store.list_queue_messages(
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
        queue="worker",
        unclaimed_only=False,
        unread_only=True,
    )
    refreshed_issue = asyncio.run(store._show_issue("at-epic.1"))
    snapshot = {
        "claimed": {
            "assignee": claimed["assignee"],
            "status": claimed["status"],
            "labels": tuple(sorted(str(label) for label in claimed["labels"])),
        },
        "finalize_reason": result.reason,
        "review": changeset_record.review.model_dump(mode="json"),
        "changeset_status": changeset_record.lifecycle.value,
        "changeset_labels": tuple(sorted(changeset_record.labels)),
        "hooked_before_clear": hooked_before_clear,
        "hooked_after_clear": worker_store.get_agent_hook(
            "at-agent",
            beads_root=_BEADS_ROOT,
            repo_root=_REPO_ROOT,
        ),
        "queue_after": tuple(
            (item["id"], item["queue"], item["claimed_by"]) for item in queue_after
        ),
        "unread_queue_after": tuple(item["id"] for item in unread_queue_after),
        "note_present": "worker_contract: parity verified" in (refreshed_issue.description or ""),
    }

    assert snapshot == {
        "claimed": {
            "assignee": _AGENT_ID,
            "status": "in_progress",
            "labels": ("at:epic", "at:hooked", "atelier"),
        },
        "finalize_reason": "changeset_complete",
        "review": {
            "pr_url": "https://example.invalid/pr/41",
            "pr_number": 41,
            "pr_state": "merged",
            "review_owner": "reviewer-b",
            "integrated_sha": "abc1234",
        },
        "changeset_status": "closed",
        "changeset_labels": ("atelier", "cs:merged"),
        "hooked_before_clear": "at-epic",
        "hooked_after_clear": None,
        "queue_after": (("msg-queue", "worker", _AGENT_ID),),
        "unread_queue_after": (),
        "note_present": True,
    }

    worker_store.clear_bundle_cache()


def test_worker_store_migration_docs_publish_boundary_and_deferred_gaps() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    planner_doc = PLANNER_DOC_PATH.read_text(encoding="utf-8")
    store_doc = STORE_DOC_PATH.read_text(encoding="utf-8")
    startup_skill = (SKILLS_DIR / "startup-contract" / "SKILL.md").read_text(encoding="utf-8")
    claim_skill = (SKILLS_DIR / "claim-epic" / "SKILL.md").read_text(encoding="utf-8")
    release_skill = (SKILLS_DIR / "release-epic" / "SKILL.md").read_text(encoding="utf-8")
    work_done_skill = (SKILLS_DIR / "work-done" / "SKILL.md").read_text(encoding="utf-8")
    hook_status_skill = (SKILLS_DIR / "hook-status" / "SKILL.md").read_text(encoding="utf-8")
    queue_claim_skill = (SKILLS_DIR / "mail-queue-claim" / "SKILL.md").read_text(encoding="utf-8")
    mark_read_skill = (SKILLS_DIR / "mail-mark-read" / "SKILL.md").read_text(encoding="utf-8")

    assert "Worker Store Migration Contract" in doc
    assert "Proven Worker Boundary" in doc
    assert "Worker Compatibility Seams" in doc
    assert "thread_id=None" in doc
    assert "worktree and branch metadata writes still go through" in doc
    assert "epic-close and lineage-repair fallback reads still use" in doc
    assert "publish/integration orchestration migrations onto `atelier.store`" in doc
    assert "`work-done` still closes epics through the deterministic Beads helper" in doc

    assert "[Worker Store Migration Contract]" in planner_doc
    assert "[Worker Store Migration Contract]" in store_doc

    assert "[Worker Store Migration Contract]" in startup_skill
    assert "store-backed hook model" in startup_skill
    assert "worker store adapter" in startup_skill
    assert "[Worker Store Migration Contract]" in claim_skill
    assert "store-backed claim/hook" in claim_skill
    assert "hook resolves to `<epic_id>`" in claim_skill
    assert "[Worker Store Migration Contract]" in release_skill
    assert "worker-side release boundary" in release_skill
    assert "[Worker Store Migration Contract]" in work_done_skill
    assert "compatibility path" in work_done_skill
    assert "[Worker Store Migration Contract]" in hook_status_skill
    assert "[Worker Store Migration Contract]" in queue_claim_skill
    assert "worker-side queue boundary" in queue_claim_skill
    assert "[Worker Store Migration Contract]" in mark_read_skill
    assert "worker-side unread transition" in mark_read_skill
