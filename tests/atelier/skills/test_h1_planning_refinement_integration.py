from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from atelier.lib.beads import ShowIssueRequest
from tests.atelier.skills.h1_store_harness import issue_builder, make_store_for_backend


def _load_script_module(skill: str, script: str, module_name: str):
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / skill
        / "scripts"
        / script
    )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("backend", ["in-memory", "subprocess"])
def test_h1_set_refinement_persists_authoritative_note_to_real_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backend: str,
) -> None:
    module = _load_script_module(
        "plan-set-refinement", "set_refinement.py", f"set_refinement_{backend}"
    )
    client, store = make_store_for_backend(
        backend,
        issues=(
            issue_builder.issue(
                "at-123",
                title="Refinement target",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
        ),
    )
    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "set_refinement.py",
            "--issue-id",
            "at-123",
            "--required",
            "--approval-source",
            "operator",
            "--approved-by",
            "planner-user",
            "--approved-at",
            "2026-03-29T12:00:00Z",
            "--latest-verdict",
            "READY",
        ],
    )

    module.main()

    issue = asyncio.run(client.show(ShowIssueRequest(issue_id="at-123")))
    description = str(getattr(issue, "description", "") or "")
    assert "planning_refinement.v1" in description
    assert "required: true" in description
    assert "latest_verdict: READY" in description


def test_h1_promote_epic_blocks_refined_epic_without_ready_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module("plan-promote-epic", "promote_epic.py", "promote_epic_h1")
    _client, store = make_store_for_backend(
        "in-memory",
        issues=(
            issue_builder.issue(
                "at-epic",
                title="Promote me",
                issue_type="epic",
                status="deferred",
                labels=("at:epic",),
                description=(
                    "changeset_strategy: Keep review scope small.\n"
                    "related_context: at-context\n"
                    "promotion_note: ready for confirmation\n"
                    "\nplanning_refinement.v1\n"
                    "authoritative: true\n"
                    "mode: requested\n"
                    "required: true\n"
                    "approval_status: approved\n"
                    "approval_source: operator\n"
                    "approved_by: planner-user\n"
                    "approved_at: 2026-03-29T12:00:00Z\n"
                    "latest_verdict: REVISED\n"
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None)
    )
    monkeypatch.setattr(module, "_build_store_and_client", lambda **_kwargs: (store, _client))
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
