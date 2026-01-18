import os
import shlex

from .models import EditorConfig, ProjectConfig


def system_editor_default() -> str:
    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor:
        return env_editor
    return "vi"


def resolve_editor_command(config: ProjectConfig | EditorConfig | dict) -> list[str]:
    if isinstance(config, ProjectConfig):
        editor_config = config.editor
    elif isinstance(config, EditorConfig):
        editor_config = config
    else:
        editor_default = config.get("editor", {}).get("default")
        if editor_default:
            options = (
                config.get("editor", {}).get("options", {}).get(editor_default, [])
            )
            if not isinstance(options, list):
                options = []
            return [editor_default, *options]
        return shlex.split(system_editor_default())

    editor_default = editor_config.default
    if editor_default:
        options = editor_config.options.get(editor_default, [])
        return [editor_default, *options]

    return shlex.split(system_editor_default())
