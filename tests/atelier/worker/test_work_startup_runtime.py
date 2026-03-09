from pathlib import Path

from atelier import beads
from atelier.testing.beads import InMemoryBeadsBackend, IssueFixtureBuilder, patch_in_memory_beads
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
    backend = InMemoryBeadsBackend(
        seeded_issues=(
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
    )
    monkeypatch.setenv("ATELIER_AGENT_ID", agent_id)

    with patch_in_memory_beads(backend):
        beads.set_agent_hook("at-agent", "at-epic", beads_root=beads_root, cwd=repo_root)

        hooked = work_startup_runtime.resolve_hooked_epic(
            "at-agent",
            agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )

    assert hooked == "at-epic"
