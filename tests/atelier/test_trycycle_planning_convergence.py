from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONVERGENCE_DOC = _REPO_ROOT / "docs" / "trycycle-planning-convergence.md"
_BEHAVIOR_DOC = _REPO_ROOT / "docs" / "behavior.md"
_ANCHOR_FIXTURE = (
    _REPO_ROOT / "tests" / "atelier" / "fixtures" / "trycycle_refinement" / "reference_anchors.json"
)


def _read_anchor_fixture() -> dict[str, list[str]]:
    return json.loads(_ANCHOR_FIXTURE.read_text(encoding="utf-8"))


def _assert_contains_all(content: str, expected: list[str], *, section: str) -> None:
    missing = [token for token in expected if token not in content]
    assert not missing, f"missing {section} content: {missing}"


def test_convergence_doc_has_required_inventory_and_mapping_contract() -> None:
    fixture = _read_anchor_fixture()
    content = _CONVERGENCE_DOC.read_text(encoding="utf-8")

    _assert_contains_all(
        content,
        [
            "# Trycycle Planning Convergence",
            "## Source inventory",
            "## Doctrine mapping",
            "## Mechanics mapping",
            "## Atelier adaptation rationale",
            "## Non-goals",
            "Mapped to `planning`",
            "Mapped to `refine-plan`",
        ],
        section="required headings",
    )
    _assert_contains_all(content, fixture["inventory_sources"], section="source inventory")
    _assert_contains_all(content, fixture["doctrine_anchors"], section="doctrine anchors")
    _assert_contains_all(content, fixture["mechanics_anchors"], section="mechanics anchors")


def test_behavior_doc_documents_refinement_activation_lineage_and_claim_gate() -> None:
    content = _BEHAVIOR_DOC.read_text(encoding="utf-8")
    _assert_contains_all(
        content,
        [
            "Planning and refinement",
            "`planning` is the default planning doctrine",
            "`refine-plan` runs bounded iterative refinement",
            "`plan-set-refinement` can enable refinement",
            "Refinement metadata is inherited by lineage descendants",
            "Worker claim fails closed when required refinement evidence",
        ],
        section="behavior refinements",
    )
