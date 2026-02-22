from __future__ import annotations

from pathlib import Path

from atelier import commit_messages


def test_validate_conventional_commit_header_accepts_valid_header() -> None:
    assert (
        commit_messages.validate_conventional_commit_header("feat(worker): bootstrap hooks") is None
    )


def test_validate_conventional_commit_header_rejects_missing_scope() -> None:
    error = commit_messages.validate_conventional_commit_header("feat: bootstrap hooks")
    assert error is not None
    assert "<type>(<scope>): <subject>" in error


def test_validate_conventional_commit_header_rejects_unknown_type() -> None:
    error = commit_messages.validate_conventional_commit_header("unknown(worker): bootstrap hooks")
    assert error is not None
    assert "unsupported commit type" in error


def test_validate_commit_message_file_uses_first_non_comment_line(tmp_path: Path) -> None:
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text(
        "# comment\n\nfeat(worker): bootstrap hooks\n\nbody\n",
        encoding="utf-8",
    )
    assert commit_messages.validate_commit_message_file(message_file) is None
