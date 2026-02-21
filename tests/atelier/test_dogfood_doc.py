from __future__ import annotations

from pathlib import Path


def test_dogfood_doc_exists() -> None:
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "dogfood.md"
    content = doc_path.read_text(encoding="utf-8")
    assert "Golden Path" in content
    assert "keeps the epic as the executable changeset" in content
