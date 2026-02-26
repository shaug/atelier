import tempfile
from pathlib import Path

from atelier.models import BeadsSection, BranchConfig, ProjectUserConfig


class TestEditorConfig:
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
            assert parsed.editor.edit == [str(editor_path), "-w"]
            assert parsed.editor.work == [str(editor_path)]


def test_branch_config_defaults_pr_mode_to_none() -> None:
    config = BranchConfig()
    assert config.pr_mode == "none"
    assert config.pr is False


def test_branch_config_maps_legacy_pr_bool_to_pr_mode() -> None:
    enabled = BranchConfig.model_validate({"pr": True})
    disabled = BranchConfig.model_validate({"pr": False})
    assert enabled.pr_mode == "draft"
    assert disabled.pr_mode == "none"


def test_beads_section_normalizes_server_runtime_aliases() -> None:
    parsed = BeadsSection.model_validate({"runtime_mode": "server"})
    assert parsed.runtime_mode == "dolt-server"


def test_beads_section_migrates_legacy_mode_key() -> None:
    parsed = BeadsSection.model_validate({"mode": "dolt_server"})
    assert parsed.runtime_mode == "dolt-server"
