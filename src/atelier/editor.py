"""Editor resolution utilities for Atelier."""

import os
import shlex

from .models import EditorConfig, ProjectConfig


def system_editor_default() -> str:
    """Return the default editor command.

    Uses ``$EDITOR`` when set; otherwise falls back to ``vi``.

    Returns:
        Editor command string.

    Example:
        >>> isinstance(system_editor_default(), str)
        True
    """
    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor:
        return env_editor
    return "vi"


def resolve_editor_command(config: ProjectConfig | EditorConfig | dict) -> list[str]:
    """Resolve the editor command and options to execute.

    Args:
        config: ``ProjectConfig``, ``EditorConfig``, or raw dict containing
            editor defaults and options.

    Returns:
        List of command tokens suitable for ``subprocess`` execution.

    Example:
        >>> resolve_editor_command({"editor": {"default": "vim", "options": {}}})
        ['vim']
    """
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
