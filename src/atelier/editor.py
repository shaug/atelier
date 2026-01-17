import os
import shlex


def system_editor_default() -> str:
    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor:
        return env_editor
    return "vi"


def resolve_editor_command(config: dict) -> list[str]:
    editor_default = config.get("editor", {}).get("default")
    if editor_default:
        options = config.get("editor", {}).get("options", {}).get(editor_default, [])
        if not isinstance(options, list):
            options = []
        return [editor_default, *options]

    return shlex.split(system_editor_default())
