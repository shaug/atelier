import sys
import tempfile
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atelier.models import ProjectUserConfig  # noqa: E402


class TestEditorConfig(TestCase):
    def test_editor_config_accepts_string_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            editor_path = Path(tmp) / "My Editor.app" / "Contents" / "MacOS" / "editor"
            editor_path.parent.mkdir(parents=True, exist_ok=True)
            editor_path.write_text("", encoding="utf-8")
            payload = {
                "editor": {
                    "edit": f"{editor_path} -w",
                    "work": str(editor_path),
                }
            }
            parsed = ProjectUserConfig.model_validate(payload)
            self.assertEqual(parsed.editor.edit, [str(editor_path), "-w"])
            self.assertEqual(parsed.editor.work, [str(editor_path)])
