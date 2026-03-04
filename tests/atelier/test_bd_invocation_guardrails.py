from __future__ import annotations

import re
from pathlib import Path

from atelier import beads

_FORBIDDEN_BD_FLAG = re.compile(r"\bbd\s+--beads-dir(?:\b|=)")


def test_identity_remediation_command_uses_supported_bd_invocation() -> None:
    command = beads._identity_remediation_command(  # pyright: ignore[reportPrivateUsage]
        "at-123",
        beads_root=Path("/tmp/project/.beads"),
    )

    assert "--beads-dir" not in command


def test_runtime_and_skill_docs_do_not_embed_forbidden_bd_beads_dir_form() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        *repo_root.glob("src/atelier/**/*.py"),
        *repo_root.glob("src/atelier/skills/**/*.md"),
        repo_root / "docs" / "beads-store-parity.md",
    ]
    violations: list[str] = []
    for path in sorted(set(candidates)):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _FORBIDDEN_BD_FLAG.search(line):
                violations.append(f"{path.relative_to(repo_root)}:{line_number}: {line.strip()}")

    assert violations == []
