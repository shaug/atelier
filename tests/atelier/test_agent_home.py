import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from atelier import agent_home
from atelier.models import AgentConfig, ProjectConfig


@pytest.fixture(autouse=True)
def _clear_agent_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_AGENT_ID", raising=False)


def _assert_link_or_marker(base: Path, name: str, target: Path) -> None:
    link = base / name
    if link.is_symlink():
        assert link.resolve() == target.resolve()
        return
    marker = base / f"{name}.path"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(target)


def test_resolve_agent_home_creates_metadata_and_instructions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(project_dir, ProjectConfig(), role="worker")

        assert home.path.exists()
        assert (home.path / agent_home.AGENT_INSTRUCTIONS_FILENAME).exists()
        metadata_path = home.path / agent_home.AGENT_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["id"] == "atelier/worker/codex"
        assert payload["name"] == "codex"
        assert payload["role"] == "worker"
        assert home.path == project_dir / "agents" / "worker" / "codex"


def test_env_agent_id_overrides_default_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with patch.dict(os.environ, {"ATELIER_AGENT_ID": "atelier/worker/alice"}):
            home = agent_home.resolve_agent_home(project_dir, ProjectConfig(), role="worker")
        assert home.name == "alice"
        assert home.agent_id == "atelier/worker/alice"
        assert home.path == project_dir / "agents" / "worker" / "alice"


def test_resolve_agent_home_rejects_env_role_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with (
            patch.dict(os.environ, {"ATELIER_AGENT_ID": "atelier/planner/alice"}),
            patch("atelier.agent_home.die", side_effect=RuntimeError("die called")) as die_fn,
        ):
            with pytest.raises(RuntimeError, match="die called"):
                agent_home.resolve_agent_home(project_dir, ProjectConfig(), role="worker")
    assert "ATELIER_AGENT_ID role mismatch" in str(die_fn.call_args.args[0])
    assert "atelier/worker/<name>" in str(die_fn.call_args.args[0])


def test_preview_agent_home_rejects_env_role_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with (
            patch.dict(os.environ, {"ATELIER_AGENT_ID": "atelier/planner/alice"}),
            patch("atelier.agent_home.die", side_effect=RuntimeError("die called")) as die_fn,
        ):
            with pytest.raises(RuntimeError, match="die called"):
                agent_home.preview_agent_home(project_dir, ProjectConfig(), role="worker")
    assert "ATELIER_AGENT_ID role mismatch" in str(die_fn.call_args.args[0])
    assert "atelier/worker/<name>" in str(die_fn.call_args.args[0])


def test_config_agent_identity_is_used_when_env_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        config_payload = ProjectConfig(agent=AgentConfig(identity="atelier/worker/bob"))
        home = agent_home.resolve_agent_home(project_dir, config_payload, role="worker")
    assert home.name == "bob"
    assert home.agent_id == "atelier/worker/bob"
    assert home.path == project_dir / "agents" / "worker" / "bob"


def test_session_agent_home_isolated_by_session_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir,
            ProjectConfig(),
            role="worker",
            session_key="p111-t222",
        )
        assert home.agent_id == "atelier/worker/codex/p111-t222"
        assert home.path == project_dir / "agents" / "worker" / "codex" / "p111-t222"
        metadata_path = home.path / agent_home.AGENT_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["session_key"] == "p111-t222"


def test_preview_agent_home_uses_session_env_var() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with patch.dict(os.environ, {agent_home.SESSION_ENV_VAR: "p10-t20"}):
            home = agent_home.preview_agent_home(
                project_dir,
                ProjectConfig(),
                role="planner",
            )
        assert home.agent_id == "atelier/planner/codex/p10-t20"
        assert home.path == project_dir / "agents" / "planner" / "codex" / "p10-t20"


def test_session_started_ns_from_agent_id_parses_timestamp() -> None:
    assert agent_home.session_started_ns_from_agent_id("atelier/worker/codex/p42-t123456") == 123456
    assert agent_home.session_started_ns_from_agent_id("atelier/worker/codex/p42") is None


def test_is_session_agent_active_rejects_pid_reuse() -> None:
    agent_id = "atelier/worker/codex/p4242-t1000"
    with (
        patch("atelier.agent_home.os.kill"),
        patch("atelier.agent_home._pid_started_ns", return_value=7_000_000_000),
    ):
        assert agent_home.is_session_agent_active(agent_id) is False


def test_is_session_agent_active_accepts_matching_process_start() -> None:
    agent_id = "atelier/worker/codex/p4242-t1000"
    with (
        patch("atelier.agent_home.os.kill"),
        patch("atelier.agent_home._pid_started_ns", return_value=2_000_000_000),
    ):
        assert agent_home.is_session_agent_active(agent_id) is True


def test_ensure_agent_links_creates_symlinks_or_markers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(project_dir, ProjectConfig(), role="worker")
        worktree = root / "worktree"
        beads = root / "beads"
        skills = root / "skills"
        worktree.mkdir()
        beads.mkdir()
        skills.mkdir()

        agent_home.ensure_agent_links(
            home,
            worktree_path=worktree,
            beads_root=beads,
            skills_dir=skills,
        )

        _assert_link_or_marker(home.path, "worktree", worktree)
        _assert_link_or_marker(home.path, "beads", beads)
        _assert_link_or_marker(home.path, "skills", skills)


def test_ensure_agent_links_creates_project_skill_aliases() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(project_dir, ProjectConfig(), role="worker")
        worktree = root / "worktree"
        beads = root / "beads"
        skills = root / "skills"
        worktree.mkdir()
        beads.mkdir()
        skills.mkdir()

        agent_home.ensure_agent_links(
            home,
            worktree_path=worktree,
            beads_root=beads,
            skills_dir=skills,
            project_skill_lookup_paths=(".agents/skills", ".claude/skills"),
        )

        _assert_link_or_marker(home.path, ".agents/skills", skills)
        _assert_link_or_marker(home.path, ".claude/skills", skills)


def test_cleanup_agent_home_removes_session_dir_and_prunes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir,
            ProjectConfig(),
            role="worker",
            session_key="p1-t2",
        )
        marker = home.path / "marker.txt"
        marker.write_text("x", encoding="utf-8")
        assert home.path.exists()

        removed = agent_home.cleanup_agent_home(home, project_dir=project_dir)

        assert removed is True
        assert not home.path.exists()
        assert not (project_dir / "agents" / "worker" / "codex").exists()


def test_cleanup_agent_home_by_id_ignores_non_session_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        removed = agent_home.cleanup_agent_home_by_id(project_dir, "atelier/worker/codex")
        assert removed is False


def test_ensure_claude_compat_writes_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agent_path = root / "agent"
        agent_path.mkdir(parents=True)
        content = "# Agent Instructions\nRule: test\n"

        agent_home.ensure_claude_compat(agent_path, content)

        claude_md = agent_path / agent_home.CLAUDE_INSTRUCTIONS_FILENAME
        assert claude_md.exists()
        assert "AGENTS.md" in claude_md.read_text(encoding="utf-8")

        hook_path = (
            agent_path
            / agent_home.CLAUDE_DIRNAME
            / agent_home.CLAUDE_HOOKS_DIRNAME
            / agent_home.CLAUDE_HOOK_SCRIPT
        )
        assert hook_path.exists()

        settings_path = agent_path / agent_home.CLAUDE_DIRNAME / agent_home.CLAUDE_SETTINGS_FILENAME
        assert settings_path.exists()


def test_ensure_claude_compat_serializes_concurrent_rewrites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agent_path = root / "agent"
        agent_path.mkdir(parents=True)

        active_lock = threading.Lock()
        start = threading.Barrier(3)
        active = 0
        max_active = 0
        failures: list[Exception] = []
        original_write = agent_home.write_text_atomic

        def wrapped_write(*args, **kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            try:
                return original_write(*args, **kwargs)
            finally:
                with active_lock:
                    active -= 1

        monkeypatch.setattr(agent_home, "write_text_atomic", wrapped_write)

        def run(content: str) -> None:
            try:
                start.wait(timeout=1.0)
                agent_home.ensure_claude_compat(agent_path, content)
            except Exception as exc:  # pragma: no cover - debugging guard
                failures.append(exc)

        thread_a = threading.Thread(target=run, args=("# Agent A\nrule: one\n",))
        thread_b = threading.Thread(target=run, args=("# Agent B\nrule: two\n",))
        thread_a.start()
        thread_b.start()
        start.wait(timeout=1.0)
        thread_a.join(timeout=3.0)
        thread_b.join(timeout=3.0)

        assert not failures
        assert max_active == 1

        settings_path = agent_path / agent_home.CLAUDE_DIRNAME / agent_home.CLAUDE_SETTINGS_FILENAME
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        assert isinstance(payload.get("hooks"), dict)


def test_apply_beads_prime_addendum_inserts_block() -> None:
    content = "# Worker Context\n\nBase instructions.\n"
    addendum = "# Beads Workflow Context\n\n- Use bd ready."

    updated = agent_home.apply_beads_prime_addendum(content, addendum)

    assert "ATELIER_BEADS_PRIME_START" in updated
    assert "Beads Runtime Addendum" in updated
    assert "- Use bd ready." in updated


def test_apply_beads_prime_addendum_replaces_existing_block() -> None:
    initial = (
        "# Worker Context\n\n"
        "<!-- ATELIER_BEADS_PRIME_START -->\n"
        "## Beads Runtime Addendum\n\n"
        "old\n"
        "<!-- ATELIER_BEADS_PRIME_END -->\n"
    )

    updated = agent_home.apply_beads_prime_addendum(initial, "new")

    assert "old" not in updated
    assert "new" in updated
    assert updated.count("ATELIER_BEADS_PRIME_START") == 1


def test_apply_beads_prime_addendum_worker_role_replaces_generic_prime_guidance() -> None:
    content = "# Worker Context\n\nBase instructions.\n"
    addendum = (
        "# Beads Workflow Context\n\n"
        "# 🚨 SESSION CLOSE PROTOCOL 🚨\n\n"
        "```\n"
        "[ ] bd close at-123\n"
        "```\n"
        "Run `bd ready` for backlog triage.\n"
    )

    updated = agent_home.apply_beads_prime_addendum(content, addendum, role="worker")

    assert "Worker Runtime Context" in updated
    assert "bd close at-123" not in updated
    assert "SESSION CLOSE PROTOCOL" not in updated
    assert "assigned epic/changeset bead is the only execution scope" in updated


def test_apply_beads_prime_addendum_planner_role_keeps_addendum_body() -> None:
    content = "# Planner Context\n\nBase instructions.\n"
    addendum = "# Beads Workflow Context\n\n- Use bd ready."

    updated = agent_home.apply_beads_prime_addendum(content, addendum, role="planner")

    assert "Use bd ready." in updated
    assert "Worker Runtime Context" not in updated
