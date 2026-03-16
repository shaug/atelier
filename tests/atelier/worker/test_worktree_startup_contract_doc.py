from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "worker-worktree-startup-contract.md"
ARCH_DOC_PATH = REPO_ROOT / "docs" / "worker-runtime-architecture.md"


def test_worker_worktree_startup_contract_doc_covers_fast_path_and_fallback() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    arch_doc = ARCH_DOC_PATH.read_text(encoding="utf-8")

    assert "Worker Worktree Startup Contract" in doc
    assert "selected-scope validation is the default startup path" in doc
    assert "global reconciliation and repair are fallback-only escape hatches" in doc
    assert "SAFE_REUSE" in doc
    assert "LOCAL_CREATE" in doc
    assert "REQUIRES_FALLBACK_REPAIR" in doc
    assert "AMBIGUOUS" in doc
    assert "fail closed" in doc.lower()
    assert "tests/atelier/worker/test_session_worktree_fast_path.py" in doc
    assert "tests/atelier/worker/test_session_worktree.py" in doc

    assert "[Worker Worktree Startup Contract]" in arch_doc
