"""Publish-gate helpers for finalize pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import FinalizeResult

_NORTH_STAR_REVIEW_HEADER_RE = re.compile(r"^north_star_review\.(?P<artifact>.+):\s*$")
_TOP_LEVEL_NOTE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*):\s*.*$")
_SECTION_HEADER_RE = re.compile(r"^\s*(?P<number>\d+)\)\s*(?P<key>[a-z_]+):\s*(?P<value>.*)$")
_NUMBERED_ACCEPTANCE_RE = re.compile(r"(?:^|\s)(?P<number>\d+)\)\s+")
_BULLET_ACCEPTANCE_RE = re.compile(r"^\s*[-*]\s+", re.MULTILINE)
_ANY_CRITERION_LINE_RE = re.compile(
    r"^\s*[-*]?\s*(?:AC\d+\b|\d+\)\s|\bcriterion\s*(?:#|no\.?\s*)?\d+\b)",
    re.IGNORECASE,
)
_EVIDENCE_TOKEN_RE = re.compile(
    (
        r"\b(commit|committed_sha|files?|verification|sha|this note|note before first push)\b|"
        r"\b[a-f0-9]{7,40}\b|"
        r"\b[\w./-]+\.(?:py|md|tmpl|json|toml|sh|yaml|yml|txt)\b"
    ),
    re.IGNORECASE,
)
_BLOCK_LOCAL_KEYS = frozenset({"authoritative", "supersedes"})
_REQUIRED_REVIEW_SECTIONS = (
    "unmet_acceptance_criteria",
    "required_code_changes_per_criterion",
    "implementation_summary",
    "completion_checklist",
)


@dataclass(frozen=True)
class NorthStarReviewGateResult:
    """Structured north-star publish-gate validation output."""

    ok: bool
    artifact_name: str | None
    summary: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _NorthStarReviewBlock:
    artifact_name: str
    text: str
    authoritative: bool


def _starts_new_note(line: str) -> bool:
    match = _TOP_LEVEL_NOTE_RE.match(line)
    if match is None:
        return False
    return match.group("key") not in _BLOCK_LOCAL_KEYS


def _extract_review_blocks(notes: str | None) -> tuple[_NorthStarReviewBlock, ...]:
    if not isinstance(notes, str) or not notes.strip():
        return ()

    blocks: list[_NorthStarReviewBlock] = []
    current_name: str | None = None
    current_lines: list[str] = []
    authoritative = False

    for raw_line in notes.splitlines():
        header_match = _NORTH_STAR_REVIEW_HEADER_RE.match(raw_line)
        if current_name is None:
            if header_match is None:
                continue
            current_name = f"north_star_review.{header_match.group('artifact')}"
            current_lines = [raw_line]
            authoritative = False
            continue

        if header_match is not None:
            blocks.append(
                _NorthStarReviewBlock(
                    artifact_name=current_name,
                    text="\n".join(current_lines).strip(),
                    authoritative=authoritative,
                )
            )
            current_name = f"north_star_review.{header_match.group('artifact')}"
            current_lines = [raw_line]
            authoritative = False
            continue

        stripped = raw_line.strip()
        if stripped.lower() == "authoritative: true":
            authoritative = True
        if _starts_new_note(raw_line):
            blocks.append(
                _NorthStarReviewBlock(
                    artifact_name=current_name,
                    text="\n".join(current_lines).strip(),
                    authoritative=authoritative,
                )
            )
            current_name = None
            current_lines = []
            authoritative = False
            continue
        current_lines.append(raw_line)

    if current_name is not None:
        blocks.append(
            _NorthStarReviewBlock(
                artifact_name=current_name,
                text="\n".join(current_lines).strip(),
                authoritative=authoritative,
            )
        )
    return tuple(blocks)


def _select_review_block(blocks: tuple[_NorthStarReviewBlock, ...]) -> _NorthStarReviewBlock | None:
    if not blocks:
        return None
    authoritative_blocks = [block for block in blocks if block.authoritative]
    if authoritative_blocks:
        return authoritative_blocks[-1]
    return blocks[-1]


def _parse_review_sections(block_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for raw_line in block_text.splitlines()[1:]:
        stripped = raw_line.strip()
        if stripped.startswith("authoritative:") or stripped.startswith("supersedes:"):
            continue
        section_match = _SECTION_HEADER_RE.match(raw_line)
        if section_match is not None:
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = section_match.group("key")
            value = section_match.group("value").strip()
            current_lines = [value] if value else []
            continue
        if current_key is not None:
            current_lines.append(stripped)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


def _acceptance_criteria_count(issue: dict[str, object]) -> int:
    raw = issue.get("acceptance_criteria") or issue.get("acceptance")
    if not isinstance(raw, str):
        return 0
    text = raw.strip()
    if not text:
        return 0
    numbered = _NUMBERED_ACCEPTANCE_RE.findall(text)
    if numbered:
        return len(numbered)
    bullets = _BULLET_ACCEPTANCE_RE.findall(text)
    if bullets:
        return len(bullets)
    return 1


def _criterion_patterns(index: int) -> tuple[re.Pattern[str], ...]:
    return (
        re.compile(rf"\bAC{index}\b", re.IGNORECASE),
        re.compile(rf"\bcriterion\s*(?:#|no\.?\s*)?{index}\b", re.IGNORECASE),
        re.compile(rf"^\s*[-*]?\s*{index}\)\s", re.IGNORECASE),
    )


def _mentions_criterion(text: str, index: int) -> bool:
    return any(pattern.search(text) for pattern in _criterion_patterns(index))


def _criterion_entry(section_text: str, index: int) -> str | None:
    entries: list[list[str]] = []
    current: list[str] = []
    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if _ANY_CRITERION_LINE_RE.search(stripped):
            if current:
                entries.append(current)
            current = [stripped]
            continue
        if current:
            current.append(stripped)
    if current:
        entries.append(current)

    for entry_lines in entries:
        entry = "\n".join(entry_lines)
        if _mentions_criterion(entry, index):
            return entry
    if _mentions_criterion(section_text, index):
        return section_text
    return None


def _missing_section_criteria(section_text: str, count: int) -> tuple[str, ...]:
    missing: list[str] = []
    for index in range(1, count + 1):
        if not _mentions_criterion(section_text, index):
            missing.append(f"AC{index}")
    return tuple(missing)


def _missing_evidence_criteria(section_text: str, count: int) -> tuple[str, ...]:
    missing: list[str] = []
    for index in range(1, count + 1):
        entry = _criterion_entry(section_text, index)
        if entry is None:
            continue
        if _EVIDENCE_TOKEN_RE.search(entry) is None:
            missing.append(f"AC{index}")
    return tuple(missing)


def _normalized_section_value(value: str) -> str:
    parts: list[str] = []
    for raw_line in value.splitlines():
        stripped = raw_line.strip().strip("-*`")
        if stripped:
            parts.append(stripped)
    return " ".join(parts).strip().lower()


def validate_north_star_review_gate(issue: dict[str, object]) -> NorthStarReviewGateResult:
    """Validate the active bead's north-star review artifact before publish.

    Args:
        issue: Active changeset bead payload from ``bd show --json``.

    Returns:
        Validation outcome with an auditable summary and operator-readable
        diagnostics.
    """
    notes = issue.get("notes")
    blocks = _extract_review_blocks(notes if isinstance(notes, str) else "")
    block = _select_review_block(blocks)
    if block is None:
        return NorthStarReviewGateResult(
            ok=False,
            artifact_name=None,
            summary="missing `north_star_review.<timestamp>` note in bead notes",
            diagnostics=(
                "Missing required `north_star_review.<timestamp>:` note in the changeset bead.",
            ),
        )

    sections = _parse_review_sections(block.text)
    diagnostics: list[str] = [f"Selected artifact: `{block.artifact_name}`."]

    missing_sections = [
        section for section in _REQUIRED_REVIEW_SECTIONS if not sections.get(section, "").strip()
    ]
    if missing_sections:
        diagnostics.append(
            "Missing required review sections: "
            f"{', '.join(f'`{section}`' for section in missing_sections)}."
        )

    criteria_count = _acceptance_criteria_count(issue)
    if criteria_count <= 0:
        diagnostics.append("Active bead is missing acceptance criteria needed for checklist audit.")

    unmet_value = sections.get("unmet_acceptance_criteria", "")
    if unmet_value and _normalized_section_value(unmet_value) not in {"none", "[]"}:
        diagnostics.append(
            f"`unmet_acceptance_criteria` must be `none`; found: {unmet_value.strip()}."
        )

    required_map = sections.get("required_code_changes_per_criterion", "")
    checklist = sections.get("completion_checklist", "")
    missing_required_map = _missing_section_criteria(required_map, criteria_count)
    if missing_required_map:
        diagnostics.append(
            "`required_code_changes_per_criterion` is missing criterion mapping for "
            f"{', '.join(missing_required_map)}."
        )

    missing_checklist = _missing_section_criteria(checklist, criteria_count)
    if missing_checklist:
        diagnostics.append(
            "`completion_checklist` is missing criterion coverage for "
            f"{', '.join(missing_checklist)}."
        )

    missing_evidence = _missing_evidence_criteria(checklist, criteria_count)
    if missing_evidence:
        diagnostics.append(
            f"`completion_checklist` is missing evidence tokens for {', '.join(missing_evidence)}."
        )

    if len(diagnostics) > 1:
        return NorthStarReviewGateResult(
            ok=False,
            artifact_name=block.artifact_name,
            summary="north-star review artifact is incomplete for publish",
            diagnostics=tuple(diagnostics),
        )

    return NorthStarReviewGateResult(
        ok=True,
        artifact_name=block.artifact_name,
        summary=(
            f"north-star review gate satisfied by `{block.artifact_name}` "
            f"for {criteria_count} acceptance criteria"
        ),
    )


def review_pending_result() -> FinalizeResult:
    """Return the canonical review-pending finalize result."""
    return FinalizeResult(continue_running=True, reason="changeset_review_pending")
