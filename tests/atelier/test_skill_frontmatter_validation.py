from __future__ import annotations

from pathlib import Path

import atelier.skill_frontmatter_validation as validator


def _write_skill(
    skills_root: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str | None = "Valid description",
    raw_frontmatter: str | None = None,
) -> Path:
    skill_dir = skills_root / directory
    skill_dir.mkdir(parents=True)
    doc = skill_dir / "SKILL.md"
    if raw_frontmatter is not None:
        doc.write_text(raw_frontmatter, encoding="utf-8")
        return doc
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.extend(["---", "", "# Skill"])
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


def _rules(violations: tuple[validator.SkillFrontmatterViolation, ...]) -> set[str]:
    return {item.rule for item in violations}


def test_validate_skill_frontmatter_accepts_valid_block_scalar_description(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    doc = _write_skill(
        skills_root,
        "valid-skill",
        raw_frontmatter=(
            "---\nname: valid-skill\ndescription: >-\n  First line\n  second line\n---\n\n# Skill\n"
        ),
    )
    violations = validator.validate_skill_frontmatter(doc, project_root=tmp_path)
    assert not violations


def test_validate_skill_frontmatter_reports_missing_name_and_empty_description(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    doc = _write_skill(skills_root, "missing-name", name=None, description="   ")
    violations = validator.validate_skill_frontmatter(doc, project_root=tmp_path)
    assert _rules(violations) == {"name.required", "description.empty"}


def test_validate_skill_frontmatter_reports_name_format_and_directory_mismatch(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    doc = _write_skill(
        skills_root,
        "valid-dir",
        name="invalid_name",
        description="desc",
    )
    violations = validator.validate_skill_frontmatter(doc, project_root=tmp_path)
    assert _rules(violations) == {"name.format", "name.parent_directory"}


def test_validate_skill_frontmatter_reports_length_violations(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    long_name = "a" * 65
    long_description = "d" * 1025
    doc = _write_skill(
        skills_root,
        "a" * 65,
        name=long_name,
        description=long_description,
    )
    violations = validator.validate_skill_frontmatter(doc, project_root=tmp_path)
    assert _rules(violations) == {"description.length", "name.length"}


def test_compare_to_baseline_flags_unexpected_and_tracks_resolved() -> None:
    violations = (
        validator.SkillFrontmatterViolation(
            path="src/atelier/skills/new-skill/SKILL.md",
            rule="name.format",
            message="bad format",
        ),
        validator.SkillFrontmatterViolation(
            path="src/atelier/skills/old-skill/SKILL.md",
            rule="description.required",
            message="missing description",
        ),
    )
    allowed = {
        ("src/atelier/skills/old-skill/SKILL.md", "description.required"),
        ("src/atelier/skills/resolved/SKILL.md", "name.format"),
    }
    unexpected, resolved = validator.compare_to_baseline(violations, allowed)
    assert len(unexpected) == 1
    assert unexpected[0].path == "src/atelier/skills/new-skill/SKILL.md"
    assert unexpected[0].rule == "name.format"
    assert resolved == (("src/atelier/skills/resolved/SKILL.md", "name.format"),)


def test_packaged_skills_have_no_unexpected_baseline_violations() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    skills_root = repo_root / "src/atelier/skills"
    baseline_path = skills_root / "validation-baseline.json"
    violations = validator.validate_skills_tree(skills_root, project_root=repo_root)
    allowed = validator.load_validation_baseline(baseline_path)
    unexpected, _resolved = validator.compare_to_baseline(violations, allowed)
    assert not unexpected
