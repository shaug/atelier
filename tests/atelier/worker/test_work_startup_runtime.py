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


def test_next_changeset_service_lists_work_children_via_store_adapter(monkeypatch) -> None:
    expected_child = {"id": "at-epic.1"}

    def _raise_on_raw_beads(*_args, **_kwargs):
        raise AssertionError("raw beads.list_work_children should not be used during startup")

    monkeypatch.setattr(work_startup_runtime.beads, "list_work_children", _raise_on_raw_beads)
    monkeypatch.setattr(
        worker_store,
        "list_work_children",
        lambda parent_id, *, beads_root, repo_root, include_closed: (
            [expected_child]
            if (
                parent_id == "at-epic"
                and beads_root == Path("/beads")
                and repo_root == Path("/repo")
                and include_closed is True
            )
            else []
        ),
    )

    service = work_startup_runtime._NextChangesetService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert service.list_work_children("at-epic", include_closed=True) == [expected_child]


def test_startup_contract_service_lists_work_children_via_store_adapter(monkeypatch) -> None:
    expected_child = {"id": "at-epic.1"}

    def _raise_on_raw_beads(*_args, **_kwargs):
        raise AssertionError("raw beads.list_work_children should not be used during startup")

    monkeypatch.setattr(work_startup_runtime.beads, "list_work_children", _raise_on_raw_beads)
    monkeypatch.setattr(
        worker_store,
        "list_work_children",
        lambda parent_id, *, beads_root, repo_root, include_closed: (
            [expected_child]
            if (
                parent_id == "at-epic"
                and beads_root == Path("/beads")
                and repo_root == Path("/repo")
                and include_closed is False
            )
            else []
        ),
    )

    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert service.list_work_children("at-epic", include_closed=False) == [expected_child]


def test_startup_contract_service_updates_integrated_sha_via_store_adapter(monkeypatch) -> None:
    def _raise_on_raw_beads(*_args, **_kwargs):
        raise AssertionError(
            "raw beads.update_changeset_integrated_sha should not be used during startup"
        )

    calls: list[tuple[str, str, Path, Path, bool]] = []
    monkeypatch.setattr(
        work_startup_runtime.beads,
        "update_changeset_integrated_sha",
        _raise_on_raw_beads,
    )
    monkeypatch.setattr(
        worker_store,
        "update_changeset_integrated_sha",
        lambda changeset_id, integrated_sha, *, beads_root, repo_root, allow_override=False: (
            calls.append((changeset_id, integrated_sha, beads_root, repo_root, allow_override))
        ),
    )

    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    service.update_changeset_integrated_sha("at-epic.1", "abc1234")

    assert calls == [("at-epic.1", "abc1234", Path("/beads"), Path("/repo"), True)]
