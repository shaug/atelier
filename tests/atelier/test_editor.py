import tempfile
from pathlib import Path

import pytest

import atelier.editor as editor


class TestResolveEditorCommand:
    def test_config_precedence(self) -> None:
        config = {"editor": {"edit": ["cursor", "-w"], "work": ["code"]}}
        assert editor.resolve_editor_command(config, role="edit") == ["cursor", "-w"]

    def test_work_role(self) -> None:
        config = {"editor": {"edit": ["cursor", "-w"], "work": ["code"]}}
        assert editor.resolve_editor_command(config, role="work") == ["code"]

    def test_missing_role_errors(self) -> None:
        with pytest.raises(SystemExit):
            editor.resolve_editor_command({"editor": {"edit": ["cursor"]}}, role="work")

    def test_string_command_with_space_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            editor_path = Path(tmp) / "My Editor.app" / "Contents" / "MacOS" / "editor"
            editor_path.parent.mkdir(parents=True, exist_ok=True)
            editor_path.write_text("", encoding="utf-8")
            config_payload = {
                "editor": {
                    "edit": f"{editor_path} -w",
                    "work": str(editor_path),
                }
            }
            assert editor.resolve_editor_command(config_payload, role="edit") == [
                str(editor_path),
                "-w",
            ]
            assert editor.resolve_editor_command(config_payload, role="work") == [
                str(editor_path)
            ]
