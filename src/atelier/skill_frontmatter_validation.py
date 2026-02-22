"""Validate AgentSkills frontmatter for packaged skills."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
DEFAULT_BASELINE_PATH = DEFAULT_SKILLS_ROOT / "validation-baseline.json"


@dataclass(frozen=True)
class SkillFrontmatterViolation:
    """Represents a single skill frontmatter validation violation."""

    path: str
    rule: str
    message: str


def _display_path(path: Path, *, project_root: Path | None) -> str:
    if project_root is not None:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            pass
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_frontmatter(text: str) -> tuple[list[str] | None, str | None]:
    lines = text.splitlines()
    if not lines:
        return None, "frontmatter.missing"
    first = lines[0].lstrip("\ufeff").strip()
    if first != "---":
        return None, "frontmatter.missing"
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines[1:idx], None
    return None, "frontmatter.unclosed"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _normalize_block_lines(block_lines: list[str], style: str) -> str:
    if style.startswith(">"):
        paragraphs: list[str] = []
        current: list[str] = []
        for line in block_lines:
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                continue
            current.append(stripped)
        if current:
            paragraphs.append(" ".join(current))
        return "\n".join(paragraphs).strip()
    return "\n".join(block_lines).strip()


def _parse_frontmatter(lines: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped:
            idx += 1
            continue
        if raw.startswith(" ") or raw.startswith("\t"):
            idx += 1
            continue
        if ":" not in raw:
            idx += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            idx += 1
            continue
        if value and value[0] in {"|", ">"}:
            style = value
            block_lines: list[str] = []
            inner = idx + 1
            while inner < len(lines):
                line = lines[inner]
                if not line.strip():
                    block_lines.append("")
                    inner += 1
                    continue
                if line.startswith(" ") or line.startswith("\t"):
                    block_lines.append(line.lstrip(" \t"))
                    inner += 1
                    continue
                break
            data[key] = _normalize_block_lines(block_lines, style)
            idx = inner
            continue
        data[key] = _strip_quotes(value)
        idx += 1
    return data


def validate_skill_frontmatter(
    skill_doc: Path, *, project_root: Path | None = None
) -> tuple[SkillFrontmatterViolation, ...]:
    """Validate AgentSkills required frontmatter constraints for one skill.

    Args:
        skill_doc: Path to the skill markdown document (`SKILL.md`).
        project_root: Optional root used to render relative paths in violations.

    Returns:
        A tuple of frontmatter violations for the provided skill document.
    """
    path = _display_path(skill_doc, project_root=project_root)
    violations: list[SkillFrontmatterViolation] = []
    text = skill_doc.read_text(encoding="utf-8")
    frontmatter, frontmatter_error = _extract_frontmatter(text)
    if frontmatter_error == "frontmatter.missing":
        return (
            SkillFrontmatterViolation(
                path=path,
                rule="frontmatter.missing",
                message="Missing YAML frontmatter block delimited by '---'.",
            ),
        )
    if frontmatter_error == "frontmatter.unclosed":
        return (
            SkillFrontmatterViolation(
                path=path,
                rule="frontmatter.unclosed",
                message="Unclosed YAML frontmatter block; missing closing '---'.",
            ),
        )
    assert frontmatter is not None
    payload = _parse_frontmatter(frontmatter)
    name_present = "name" in payload
    description_present = "description" in payload
    name = payload.get("name", "").strip()
    description = payload.get("description", "")

    if not name_present or not name:
        violations.append(
            SkillFrontmatterViolation(
                path=path,
                rule="name.required",
                message="Frontmatter key 'name' is required and must be non-empty.",
            )
        )
    else:
        if len(name) > NAME_MAX_LENGTH:
            violations.append(
                SkillFrontmatterViolation(
                    path=path,
                    rule="name.length",
                    message=f"'name' must be <= {NAME_MAX_LENGTH} characters.",
                )
            )
        if not NAME_PATTERN.fullmatch(name):
            violations.append(
                SkillFrontmatterViolation(
                    path=path,
                    rule="name.format",
                    message=(
                        "'name' must use lowercase letters, digits, and hyphens only; "
                        "no leading/trailing hyphen."
                    ),
                )
            )
        parent_dir = skill_doc.parent.name
        if name != parent_dir:
            violations.append(
                SkillFrontmatterViolation(
                    path=path,
                    rule="name.parent_directory",
                    message=(f"'name' must match parent directory '{parent_dir}' exactly."),
                )
            )

    if not description_present:
        violations.append(
            SkillFrontmatterViolation(
                path=path,
                rule="description.required",
                message="Frontmatter key 'description' is required.",
            )
        )
    else:
        if not description.strip():
            violations.append(
                SkillFrontmatterViolation(
                    path=path,
                    rule="description.empty",
                    message="'description' must be non-empty after trimming whitespace.",
                )
            )
        if len(description) > DESCRIPTION_MAX_LENGTH:
            violations.append(
                SkillFrontmatterViolation(
                    path=path,
                    rule="description.length",
                    message=f"'description' must be <= {DESCRIPTION_MAX_LENGTH} characters.",
                )
            )

    return tuple(violations)


def validate_skills_tree(
    skills_root: Path, *, project_root: Path | None = None
) -> tuple[SkillFrontmatterViolation, ...]:
    """Validate frontmatter for every packaged skill under a skills directory.

    Args:
        skills_root: Directory that contains one child directory per skill.
        project_root: Optional root used to render relative paths in violations.

    Returns:
        A tuple of all skill frontmatter violations, sorted by path and rule.
    """
    violations: list[SkillFrontmatterViolation] = []
    for entry in sorted(skills_root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        skill_doc = entry / "SKILL.md"
        if not skill_doc.is_file():
            continue
        violations.extend(validate_skill_frontmatter(skill_doc, project_root=project_root))
    return tuple(sorted(violations, key=lambda item: (item.path, item.rule)))


def load_validation_baseline(path: Path) -> set[tuple[str, str]]:
    """Load allowed frontmatter violations used for incremental migration gates.

    Args:
        path: JSON file path with `allowed_violations` entries.

    Returns:
        A set of `(path, rule)` tuples that are currently tolerated.

    Raises:
        ValueError: If the baseline file is malformed.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_allowed = payload.get("allowed_violations")
    if not isinstance(raw_allowed, list):
        raise ValueError("validation baseline must contain list 'allowed_violations'")
    allowed: set[tuple[str, str]] = set()
    for item in raw_allowed:
        if not isinstance(item, dict):
            raise ValueError("validation baseline entries must be objects")
        raw_path = item.get("path")
        raw_rule = item.get("rule")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("validation baseline entry missing string 'path'")
        if not isinstance(raw_rule, str) or not raw_rule:
            raise ValueError("validation baseline entry missing string 'rule'")
        allowed.add((raw_path, raw_rule))
    return allowed


def compare_to_baseline(
    violations: tuple[SkillFrontmatterViolation, ...],
    allowed_violations: set[tuple[str, str]],
) -> tuple[tuple[SkillFrontmatterViolation, ...], tuple[tuple[str, str], ...]]:
    """Compare current violations with baseline allowances.

    Args:
        violations: Current validation violations.
        allowed_violations: Allowed `(path, rule)` tuples from baseline.

    Returns:
        A tuple containing:
        1) unexpected violations (not in baseline),
        2) resolved baseline entries not currently observed.
    """
    actual = {(item.path, item.rule) for item in violations}
    unexpected = tuple(
        sorted(
            (item for item in violations if (item.path, item.rule) not in allowed_violations),
            key=lambda item: (item.path, item.rule),
        )
    )
    resolved = tuple(sorted(allowed_violations - actual))
    return unexpected, resolved


def _print_violations(header: str, violations: tuple[SkillFrontmatterViolation, ...]) -> None:
    print(header)
    for violation in violations:
        print(f"- {violation.path}: [{violation.rule}] {violation.message}")


def _default_project_root(skills_root: Path) -> Path:
    if skills_root == DEFAULT_SKILLS_ROOT:
        return Path(__file__).resolve().parents[2]
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    """Run AgentSkills frontmatter validation for packaged skills.

    Args:
        argv: Optional CLI arguments excluding the executable name.

    Returns:
        Process exit code (`0` for success, `1` for validation failures).
    """
    parser = argparse.ArgumentParser(
        description=("Validate required AgentSkills frontmatter constraints for packaged skills.")
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=DEFAULT_SKILLS_ROOT,
        help="Skills directory to validate (default: packaged src/atelier/skills).",
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help="Fail only on violations not listed in the baseline file.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON path used with --check-baseline.",
    )
    args = parser.parse_args(argv)

    project_root = _default_project_root(args.skills_root.resolve())
    violations = validate_skills_tree(args.skills_root.resolve(), project_root=project_root)
    if args.check_baseline:
        allowed = load_validation_baseline(args.baseline.resolve())
        unexpected, resolved = compare_to_baseline(violations, allowed)
        if unexpected:
            _print_violations(
                "Unexpected AgentSkills frontmatter violations detected:",
                unexpected,
            )
            return 1
        print(
            "AgentSkills frontmatter baseline gate passed "
            f"({len(violations)} observed, {len(allowed)} allowed)."
        )
        if resolved:
            print("Resolved baseline entries detected:")
            for path, rule in resolved:
                print(f"- {path}: [{rule}]")
        return 0

    if violations:
        _print_violations("AgentSkills frontmatter violations detected:", violations)
        return 1

    print("AgentSkills frontmatter validation passed with no violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
