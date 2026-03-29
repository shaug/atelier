from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLANNING_SKILL = _REPO_ROOT / "src" / "atelier" / "skills" / "planning" / "SKILL.md"
_DOCTRINE_REFERENCE = (
    _REPO_ROOT / "src" / "atelier" / "skills" / "planning" / "references" / "planning-doctrine.md"
)
_TRYCYCLE_FIXTURE = (
    _REPO_ROOT / "tests" / "atelier" / "fixtures" / "trycycle_refinement" / "reference_anchors.json"
)


def _assert_contains_all(content: str, expected: list[str], *, label: str) -> None:
    missing = [token for token in expected if token not in content]
    assert not missing, f"missing {label}: {missing}"


def test_planning_skill_contract_mentions_doctrine_and_refinement_handoff() -> None:
    content = _PLANNING_SKILL.read_text(encoding="utf-8")
    _assert_contains_all(
        content,
        [
            "# Planning",
            "references/planning-doctrine.md",
            "intent, rationale, non-goals",
            "strategy gate",
            "low bar for replanning",
            "high bar for user interruption",
            "bite-sized",
            "execution-oriented",
        ],
        label="planning skill contract",
    )


def test_planning_doctrine_preserves_trycycle_planning_emphasis() -> None:
    fixture = json.loads(_TRYCYCLE_FIXTURE.read_text(encoding="utf-8"))
    content = _DOCTRINE_REFERENCE.read_text(encoding="utf-8")
    _assert_contains_all(content, fixture["doctrine_anchors"], label="trycycle doctrine anchors")
    _assert_contains_all(
        content,
        [
            "Intent framing",
            "Rationale capture",
            "Non-goals",
            "Strategy gate",
            "Low bar for replanning",
            "High bar for user interruption",
            "Bite-sized decomposition",
            "Execution-first task shaping",
        ],
        label="planning doctrine sections",
    )
