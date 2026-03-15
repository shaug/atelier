import asyncio
from pathlib import Path

from atelier.lib.beads import SyncBeadsClient
from atelier.store import SetHookRequest, build_atelier_store
from atelier.testing.beads import IssueFixtureBuilder
from atelier.testing.beads.client import build_in_memory_beads_client
from atelier.worker import store_adapter as worker_store
from atelier.worker import work_startup_runtime


def test_resolve_hooked_epic_uses_in_memory_slot_semantics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    builder = IssueFixtureBuilder()
    agent_id = "atelier/worker/codex/p100"
    seeded_issues = (
        builder.issue(
            "at-agent",
            issue_type="agent",
            labels=("at:agent",),
            description=f"agent_id: {agent_id}\n",
        ),
        builder.issue(
            "at-epic",
            issue_type="epic",
            labels=("at:epic", "at:hooked"),
            status="in_progress",
            assignee=agent_id,
        ),
    )
    monkeypatch.setenv("ATELIER_AGENT_ID", agent_id)
    async_client, _issue_store = build_in_memory_beads_client(issues=seeded_issues)
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
    asyncio.run(store.set_agent_hook(SetHookRequest(agent_id=agent_id, epic_id="at-epic")))

    hooked = work_startup_runtime.resolve_hooked_epic(
        "at-agent",
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )

    assert hooked == "at-epic"
    worker_store.clear_bundle_cache()
