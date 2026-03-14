from __future__ import annotations

import asyncio

from atelier.messages import render_message
from atelier.store import (
    ChangesetQuery,
    LifecycleStatus,
    MessageDelivery,
    MessageQuery,
    MessageThreadKind,
    ReadyChangesetQuery,
    ReviewState,
    build_atelier_store,
)
from atelier.testing.beads import IssueFixtureBuilder, build_in_memory_beads_client

BUILDER = IssueFixtureBuilder()


def _run(coro):
    return asyncio.run(coro)


def _store_for(*issues: dict[str, object]):
    return build_atelier_store(beads=build_in_memory_beads_client(issues=issues)[0])


def test_beads_store_reads_graphs_and_ready_changesets() -> None:
    store = _store_for(
        BUILDER.issue(
            "at-epic",
            issue_type="epic",
            labels=("at:epic",),
        ),
        BUILDER.issue("at-drift", issue_type="epic"),
        BUILDER.issue("at-parent", parent="at-epic"),
        BUILDER.issue(
            "at-change",
            parent="at-parent",
            assignee="atelier/worker/codex/p100",
            dependencies=("at-dependency",),
            description=(
                "changeset.root_branch: root/store\n"
                "changeset.parent_branch: main\n"
                "changeset.work_branch: root/store-at-change\n"
                "changeset.root_base: abc1234\n"
                "changeset.parent_base: def5678\n"
                "pr_url: https://example.invalid/pr/17\n"
                "pr_number: 17\n"
                "pr_state: in-review\n"
                "review_owner: reviewer-a\n"
                "changeset.integrated_sha: cafe1234\n"
            ),
        ),
        BUILDER.issue(
            "at-ready",
            parent="at-parent",
            dependencies=("at-merged",),
            description="pr_state: draft-pr\n",
        ),
        BUILDER.issue("at-blocked", parent="at-parent", dependencies=("at-unmerged",)),
        BUILDER.issue(
            "at-dependency",
            status="closed",
            description="pr_state: merged\n",
        ),
        BUILDER.issue("at-merged", status="closed", description="pr_state: merged\n"),
        BUILDER.issue(
            "at-unmerged",
            status="closed",
            description="pr_state: closed\n",
        ),
    )

    assert tuple(epic.id for epic in _run(store.list_epics())) == ("at-epic",)
    assert tuple(change.id for change in _run(store.get_epic("at-drift")).changesets) == (
        "at-drift",
    )
    assert tuple(change.id for change in _run(store.get_epic("at-epic")).changesets) == (
        "at-change",
        "at-ready",
        "at-blocked",
    )

    changeset = _run(store.get_changeset("at-change"))
    assert changeset.epic_id == "at-epic"
    assert changeset.lifecycle is LifecycleStatus.OPEN
    assert changeset.dependencies[0].satisfied is True
    assert changeset.branches is not None
    assert (
        changeset.branches.work_branch,
        changeset.branches.parent_base,
    ) == ("root/store-at-change", "def5678")
    assert (
        changeset.review.pr_url,
        changeset.review.pr_number,
        changeset.review.pr_state,
        changeset.review.review_owner,
        changeset.review.integrated_sha,
    ) == (
        "https://example.invalid/pr/17",
        17,
        ReviewState.IN_REVIEW,
        "reviewer-a",
        "cafe1234",
    )

    assert tuple(
        record.id for record in _run(store.list_changesets(ChangesetQuery(epic_id="at-epic")))
    ) == (
        "at-change",
        "at-ready",
        "at-blocked",
    )

    by_assignee = _run(store.list_changesets(ChangesetQuery(assignee="atelier/worker/codex/p100")))
    assert tuple(record.id for record in by_assignee) == ("at-change",)

    assert tuple(
        record.id
        for record in _run(store.list_ready_changesets(ReadyChangesetQuery(epic_id="at-epic")))
    ) == ("at-change", "at-ready")
    assert tuple(record.id for record in _run(store.list_ready_changesets())) == (
        "at-change",
        "at-ready",
    )


def test_beads_store_lists_messages_and_agent_hooks() -> None:
    store = _store_for(
        BUILDER.issue(
            "at-epic",
            issue_type="epic",
            labels=("at:epic",),
        ),
        BUILDER.issue("at-epic.1", parent="at-epic"),
        BUILDER.issue(
            "msg-1",
            labels=("at:message", "at:unread"),
            description=render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "delivery": "work-threaded",
                    "thread": "at-epic.1",
                    "thread_kind": "changeset",
                    "audience": ["planner"],
                    "queue": "planner",
                    "claimed_by": "agent-1",
                    "claimed_at": "2025-01-01T00:00:01Z",
                },
                "Need review coverage.",
            ),
        ),
        BUILDER.issue(
            "msg-2",
            labels=("at:message", "at:unread"),
            assignee="atelier/planner/codex/p200",
            description=render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "thread": "at-epic.1",
                    "thread_kind": "changeset",
                },
                "Legacy assignee routing should normalize to planner.",
            ),
        ),
        BUILDER.issue(
            "msg-3",
            labels=("at:message",),
            description=render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "delivery": "work-threaded",
                    "thread": "at-epic.1",
                    "thread_kind": "changeset",
                    "audience": ["planner"],
                },
                "This one is not unread.",
            ),
        ),
        BUILDER.issue(
            "msg-4",
            labels=("at:message", "at:unread"),
            description="body without frontmatter\n",
            assignee="atelier/planner/codex/p200",
        ),
        BUILDER.issue(
            "at-agent",
            title="atelier/worker/agent",
            issue_type="agent",
            labels=("at:agent",),
            description="agent_id: atelier/worker/agent\nhook_bead: at-epic\n",
        ),
    )

    unread_for_planner = _run(
        store.list_messages(MessageQuery(unread_only=True, audience=("planner",)))
    )
    assert tuple(message.id for message in unread_for_planner) == ("msg-1", "msg-2")
    assert unread_for_planner[0].delivery is MessageDelivery.WORK_THREADED
    assert unread_for_planner[0].thread_kind is MessageThreadKind.CHANGESET

    queued = _run(store.list_messages(MessageQuery(queue="planner")))
    assert tuple(message.id for message in queued) == ("msg-1",)
    assert (queued[0].claimed_by, queued[0].claimed_at) == (
        "agent-1",
        "2025-01-01T00:00:01Z",
    )

    hook = _run(store.get_agent_hook("atelier/worker/agent"))
    assert hook is not None
    assert (hook.agent_id, hook.epic_id) == ("atelier/worker/agent", "at-epic")
