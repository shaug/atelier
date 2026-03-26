"""Contract tests for the trycycle runtime feasibility decision doc."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "trycycle-runtime-feasibility.md"


def _doc_content() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_trycycle_runtime_feasibility_doc_exists() -> None:
    content = _doc_content()
    assert "# Trycycle Runtime Feasibility for Atelier" in content
    assert "## Scope" in content
    assert "## Source Inputs" in content
    assert "## Atelier Invariants" in content
    assert "## Trycycle-Derived Behaviors Under Review" in content


def test_trycycle_runtime_feasibility_doc_captures_critical_mismatches() -> None:
    content = _doc_content().lower()
    assert "shared message/ticket space" in content
    assert "subagent" in content
    assert "multiple workers" in content
    assert "operator accountability" in content
    assert "pull request" in content or "pr-driven" in content
    assert "human cognitive review load" in content
    assert "## mismatch matrix" in content


def test_trycycle_runtime_feasibility_doc_records_verdict_and_follow_up_shape() -> None:
    content = _doc_content().lower()
    assert "## feasibility verdict" in content
    assert "## recommended runtime profile cut" in content
    assert "## required architectural changes" in content
    assert "## future verification floor" in content
    assert "repo-owned" in content
    assert "runtime profile" in content
    assert "not currently feasible" in content
