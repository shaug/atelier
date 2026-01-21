"""Editor resolution utilities for Atelier."""

import os
import shlex

from .io import die
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


def resolve_editor_command(
    config: ProjectConfig | EditorConfig | dict, *, role: str = "edit"
) -> list[str]:
    """Resolve the editor command for the requested role.

    Args:
        config: ``ProjectConfig``, ``EditorConfig``, or raw dict containing
            editor configuration.
        role: Editor role to resolve (``edit`` or ``work``).

    Returns:
        List of command tokens suitable for ``subprocess`` execution.

    Example:
        >>> resolve_editor_command({"editor": {"edit": ["vim"]}})
        ['vim']
    """
    if role not in {"edit", "work"}:
        raise ValueError(f"unsupported editor role {role!r}")
    if isinstance(config, ProjectConfig):
        editor_config = config.editor
    elif isinstance(config, EditorConfig):
        editor_config = config
    else:
        editor_config = config.get("editor", {})

    if isinstance(editor_config, EditorConfig):
        command = editor_config.edit if role == "edit" else editor_config.work
    else:
        command = editor_config.get(role)

    if not command:
        die(f"missing editor.{role} command; run 'atelier config --prompt' to set it")
    if isinstance(command, str):
        command = shlex.split(command)
    if not isinstance(command, list) or not command:
        die(f"invalid editor.{role} command; must be a list of arguments")
    return [str(item) for item in command]
