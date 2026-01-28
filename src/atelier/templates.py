"""Template loading and rendering helpers."""

from importlib import resources
from pathlib import Path

from . import paths

TEMPLATE_PARTS: tuple[tuple[str, ...], ...] = (
    ("AGENTS.md",),
    ("project", "PROJECT.md"),
    ("workspace", "SUCCESS.md"),
    ("workspace", "SUCCESS.ticket.md"),
)


def _read_template(*parts: str) -> str:
    """Read a bundled template file from the package.

    Args:
        *parts: Path components under ``atelier/templates``.

    Returns:
        Template text.

    Example:
        >>> isinstance(_read_template("AGENTS.md"), str)
        True
    """
    return (
        resources.files("atelier")
        .joinpath("templates")
        .joinpath(*parts)
        .read_text(encoding="utf-8")
    )


def _installed_template_path(*parts: str) -> Path:
    return paths.installed_templates_dir().joinpath(*parts)


def read_installed_template(*parts: str) -> str | None:
    """Read a template from the installed cache when present.

    Args:
        *parts: Path components under the installed template cache.

    Returns:
        Template text or ``None`` when missing.
    """
    path = _installed_template_path(*parts)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def read_template(
    *parts: str,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Read a template from the installed cache or packaged defaults.

    Args:
        *parts: Path components under ``atelier/templates``.
        prefer_installed: When true, read from the installed cache if present.
        prefer_installed_if_modified: When true, prefer the installed cache only
            if it differs from the packaged default.

    Returns:
        Template text.
    """
    if prefer_installed:
        cached = read_installed_template(*parts)
        if cached is not None:
            return cached
    if prefer_installed_if_modified:
        cached = read_installed_template(*parts)
        if cached is not None:
            packaged = _read_template(*parts)
            if cached != packaged:
                return cached
            return packaged
    return _read_template(*parts)


def installed_template_modified(*parts: str) -> bool:
    """Return true when the installed cache differs from packaged defaults."""
    cached = read_installed_template(*parts)
    if cached is None:
        return False
    return cached != _read_template(*parts)


def refresh_installed_templates() -> list[Path]:
    """Refresh the installed template cache from the packaged defaults.

    Returns:
        List of paths written to the cache.
    """
    dest_root = paths.installed_templates_dir()
    written: list[Path] = []
    for parts in TEMPLATE_PARTS:
        dest = dest_root.joinpath(*parts)
        paths.ensure_dir(dest.parent)
        dest.write_text(_read_template(*parts), encoding="utf-8")
        written.append(dest)
    return written


def agents_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in agents_template()
        True
    """
    return read_template(
        "AGENTS.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def project_agents_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in project_agents_template()
        True
    """
    return read_template(
        "AGENTS.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def project_md_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the project-level ``PROJECT.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "PROJECT" in project_md_template()
        True
    """
    return read_template(
        "project",
        "PROJECT.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def workspace_agents_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in workspace_agents_template()
        True
    """
    return read_template(
        "AGENTS.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def success_md_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the workspace ``SUCCESS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "SUCCESS" in success_md_template()
        True
    """
    return read_template(
        "workspace",
        "SUCCESS.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def ticket_success_md_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the ticket-focused ``SUCCESS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "ticket" in ticket_success_md_template()
        True
    """
    return read_template(
        "workspace",
        "SUCCESS.ticket.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def render_workspace_agents() -> str:
    """Render ``AGENTS.md`` for a new workspace.

    Returns:
        Workspace ``AGENTS.md`` content.

    Example:
        >>> "Atelier" in render_workspace_agents()
        True
    """
    return workspace_agents_template(prefer_installed_if_modified=True)
