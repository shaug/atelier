from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import pytest

from atelier.lib.beads import (
    BeadsCommandRequest,
    BeadsCommandResult,
    SubprocessBeadsClient,
    SyncBeadsClient,
)
from atelier.store import (
    ExternalTicketLink,
    UpdateExternalTicketsRequest,
    build_atelier_store,
)
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)
from atelier.worker import publish as worker_publish
from atelier.worker import store_adapter as worker_store

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "publish-store-migration-contract.md"
STORE_DOC_PATH = REPO_ROOT / "docs" / "atelier-store-contract.md"
SKILLS_DIR = REPO_ROOT / "src" / "atelier" / "skills"
BUILDER = IssueFixtureBuilder()
_BACKENDS = ("in-memory", "subprocess")
_BEADS_ROOT = Path("/beads")
_REPO_ROOT = Path("/repo")


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
            title="Publish migration epic",
            issue_type="epic",
            status="open",
            labels=("at:epic", "atelier"),
        ),
        BUILDER.issue(
            "at-epic.1",
            title="Publish persistence slice",
            parent="at-epic",
            status="open",
            labels=("atelier",),
            description=(
                "changeset.root_branch: root/publish\n"
                "changeset.parent_branch: main\n"
                "changeset.work_branch: root/publish-at-epic.1\n"
                "pr_url: https://example.invalid/pr/41\n"
                "pr_number: 41\n"
                "pr_state: draft-pr\n"
                "review_owner: reviewer-a\n"
            ),
        ),
    )


def _bind_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: str,
):
    if backend == "in-memory":
        async_client, _ = build_in_memory_beads_client(issues=_seed_issues())
    elif backend == "subprocess":
        command_backend = InMemoryBeadsBackend(seeded_issues=_seed_issues())
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
    return store


@pytest.mark.parametrize("backend", _BACKENDS)
def test_publish_review_persistence_flows_have_dual_backend_parity(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    store = _bind_backend(monkeypatch, backend=backend)

    worker_store.update_changeset_review(
        "at-epic.1",
        pr_state="approved",
        review_owner="reviewer-b",
        preserve_existing=True,
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    worker_store.update_changeset_integrated_sha(
        "at-epic.1",
        "abc1234",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    asyncio.run(
        store.update_external_tickets(
            UpdateExternalTicketsRequest(
                issue_id="at-epic.1",
                tickets=(
                    ExternalTicketLink(
                        provider="github",
                        ticket_id="88",
                        url="https://github.com/acme/atelier/issues/88",
                        relation="primary",
                        direction="exported",
                        sync_mode="export",
                        state="open",
                        state_updated_at="2026-03-15T23:02:27Z",
                        content_updated_at="2026-03-15T23:02:27Z",
                        last_synced_at="2026-03-15T23:02:27Z",
                    ),
                    ExternalTicketLink(
                        provider="github",
                        ticket_id="91",
                        url="https://github.com/acme/atelier/issues/91",
                        relation="context",
                        direction="linked",
                        sync_mode="manual",
                        state="open",
                        state_updated_at="2026-03-15T23:02:27Z",
                    ),
                ),
            )
        )
    )

    changeset = asyncio.run(store.get_changeset("at-epic.1"))
    tickets = asyncio.run(store.get_external_tickets("at-epic.1"))
    issue = worker_store.show_issue(
        "at-epic.1",
        beads_root=_BEADS_ROOT,
        repo_root=_REPO_ROOT,
    )
    assert issue is not None
    snapshot = {
        "review": changeset.review.model_dump(mode="json"),
        "external_tickets": tuple(
            (ticket.provider, ticket.ticket_id, ticket.relation, ticket.direction, ticket.sync_mode)
            for ticket in tickets
        ),
        "labels": tuple(sorted(str(label) for label in issue["labels"])),
        "ticket_lines": tuple(
            worker_publish.render_pr_ticket_lines(
                issue,
                now=dt.datetime(2026, 3, 16, tzinfo=dt.timezone.utc),
            )
        ),
    }

    assert snapshot == {
        "review": {
            "pr_url": "https://example.invalid/pr/41",
            "pr_number": 41,
            "pr_state": "approved",
            "review_owner": "reviewer-b",
            "integrated_sha": "abc1234",
        },
        "external_tickets": (
            ("github", "88", "primary", "exported", "export"),
            ("github", "91", "context", "linked", "manual"),
        ),
        "labels": ("atelier", "ext:github"),
        "ticket_lines": ("- Fixes #88", "- Addresses #91"),
    }

    worker_store.clear_bundle_cache()


def test_publish_store_migration_docs_publish_boundary_and_deferred_gaps() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    store_doc = STORE_DOC_PATH.read_text(encoding="utf-8")
    publish_skill = (SKILLS_DIR / "publish" / "SKILL.md").read_text(encoding="utf-8")
    review_skill = (SKILLS_DIR / "changeset-review" / "SKILL.md").read_text(encoding="utf-8")
    import_skill = (SKILLS_DIR / "external-import" / "SKILL.md").read_text(encoding="utf-8")
    sync_skill = (SKILLS_DIR / "external-sync" / "SKILL.md").read_text(encoding="utf-8")
    close_skill = (SKILLS_DIR / "external-close" / "SKILL.md").read_text(encoding="utf-8")

    assert "Publish Store Migration Contract" in doc
    assert "Proven Publish Boundary" in doc
    assert "Publish Compatibility Seams" in doc
    assert "`changeset-review`" in doc
    assert "`beads.update_external_tickets()`" in doc
    assert "Future local review mode remains compatible" in doc
    assert "GitHub PR creation, PR updates, and inline review-thread mutations remain" in doc
    assert "store-owned publish/persist orchestration semantic" in doc
    assert "[Atelier Store Contract]" in doc

    assert "[Publish Store Migration Contract]" in store_doc
    assert "[Publish Store Migration Contract]" in publish_skill
    assert "store-backed review/integration" in publish_skill
    assert "[Publish Store Migration Contract]" in review_skill
    assert "`atelier.store.UpdateReviewRequest`" in review_skill
    assert "[Publish Store Migration Contract]" in import_skill
    assert "store-backed external ticket update" in import_skill
    assert "[Publish Store Migration Contract]" in sync_skill
    assert "`atelier.store.UpdateExternalTicketsRequest`" in sync_skill
    assert "[Publish Store Migration Contract]" in close_skill
    assert "store-backed update path" in close_skill
