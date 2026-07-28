#!/usr/bin/env python3
"""Validate the post-CLI Atelier plugin scaffold."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCS = {
    "atelier-name.md",
    "atelier-skill-design.md",
    "git-mailbox-contract.md",
    "implementation-plan.md",
    "mailbox-protocol-validation.md",
    "north-star.md",
    "project-policy-contract.md",
    "reset-gate-proposal.md",
}

PROHIBITED_PATHS = (
    "src/atelier",
    "tests",
    "evals",
    "CLAUDE.md",
    ".release-please-manifest.json",
    "release-please-config.json",
    "scripts/atelier-work.py",
    "scripts/hotspot_complexity_report.py",
    "scripts/repair_tool_install.py",
    "scripts/lint-gate.sh",
    "scripts/supported-python.sh",
)


def validate_manifest(errors: list[str]) -> None:
    """Validate the root Codex plugin manifest."""
    path = ROOT / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid plugin manifest: {error}")
        return

    required = {
        "name",
        "version",
        "description",
        "author",
        "skills",
        "interface",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        errors.append(f"plugin manifest missing fields: {', '.join(missing)}")
    if manifest.get("name") != "atelier":
        errors.append("plugin manifest name must be atelier")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        errors.append("plugin manifest version must be strict semver")
    if manifest.get("skills") != "./skills/":
        errors.append("plugin manifest must discover ./skills/")
    if "[TODO:" in path.read_text(encoding="utf-8"):
        errors.append("plugin manifest contains a TODO placeholder")


def validate_skill(errors: list[str]) -> None:
    """Validate the explicit Atelier skill entrypoint."""
    path = ROOT / "skills" / "atelier" / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"missing Atelier skill: {error}")
        return

    if not text.startswith("---\nname: atelier\n"):
        errors.append("Atelier skill frontmatter must begin with name: atelier")
    if "\ndescription:" not in text:
        errors.append("Atelier skill frontmatter must include a description")
    if "[TODO:" in text:
        errors.append("Atelier skill contains a TODO placeholder")
    if "The `work` and `audit` modes are not implemented yet" not in text:
        errors.append("skill must state that work and audit modes are unavailable")


def validate_reset_boundary(errors: list[str]) -> None:
    """Reject reintroduction of the archived implementation."""
    try:
        output = subprocess.check_output(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            cwd=ROOT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        errors.append(f"cannot inspect tracked repository paths: {error}")
        return

    tracked = {path for path in output.splitlines() if (ROOT / path).exists()}

    def tracks(relative: str) -> bool:
        return relative in tracked or any(path.startswith(f"{relative}/") for path in tracked)

    for relative in PROHIBITED_PATHS:
        if tracks(relative):
            errors.append(f"legacy path remains: {relative}")

    docs = {
        Path(path).name
        for path in tracked
        if path.startswith("docs/") and "/" not in path.removeprefix("docs/")
    }
    if docs != REQUIRED_DOCS:
        missing = sorted(REQUIRED_DOCS - docs)
        extra = sorted(docs - REQUIRED_DOCS)
        if missing:
            errors.append(f"required docs missing: {', '.join(missing)}")
        if extra:
            errors.append(f"legacy docs remain: {', '.join(extra)}")

    for relative in (
        ".mdformat.toml",
        "commitlint.config.cjs",
        "experiments/mailbox_protocol_v0.py",
        "experiments/codex-composition-eval",
        "LICENSE",
    ):
        if not tracks(relative):
            errors.append(f"retained reset evidence missing: {relative}")


def main() -> int:
    """Run every reset-scaffold validation."""
    errors: list[str] = []
    validate_manifest(errors)
    validate_skill(errors)
    validate_reset_boundary(errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Atelier reset scaffold is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
