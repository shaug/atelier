"""Template loading and rendering helpers."""

from importlib import resources
from pathlib import Path

from . import paths

TEMPLATE_PARTS: tuple[tuple[str, ...], ...] = (
    ("AGENTS.md",),
    ("project", "PROJECT.md"),
    ("workspace", "SUCCESS.md"),
    ("workspace", "PERSIST.md"),
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


def read_template(*parts: str, prefer_installed: bool = False) -> str:
    """Read a template from the installed cache or packaged defaults.

    Args:
        *parts: Path components under ``atelier/templates``.
        prefer_installed: When true, read from the installed cache if present.

    Returns:
        Template text.
    """
    if prefer_installed:
        cached = read_installed_template(*parts)
        if cached is not None:
            return cached
    return _read_template(*parts)


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


def agents_template(*, prefer_installed: bool = False) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in agents_template()
        True
    """
    return read_template("AGENTS.md", prefer_installed=prefer_installed)


def project_agents_template(*, prefer_installed: bool = False) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in project_agents_template()
        True
    """
    return read_template("AGENTS.md", prefer_installed=prefer_installed)


def project_md_template(*, prefer_installed: bool = False) -> str:
    """Return the project-level ``PROJECT.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "PROJECT" in project_md_template()
        True
    """
    return read_template("project", "PROJECT.md", prefer_installed=prefer_installed)


def workspace_agents_template(*, prefer_installed: bool = False) -> str:
    """Return the canonical ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in workspace_agents_template()
        True
    """
    return read_template("AGENTS.md", prefer_installed=prefer_installed)


def success_md_template(*, prefer_installed: bool = False) -> str:
    """Return the workspace ``SUCCESS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "SUCCESS" in success_md_template()
        True
    """
    return read_template("workspace", "SUCCESS.md", prefer_installed=prefer_installed)


def persist_template(*, prefer_installed: bool = False) -> str:
    """Return the workspace ``PERSIST.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "PERSIST" in persist_template()
        True
    """
    return read_template("workspace", "PERSIST.md", prefer_installed=prefer_installed)


def render_integration_strategy(branch_pr: bool, branch_history: str) -> str:
    """Render the integration strategy section for a workspace.

    Args:
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).

    Returns:
        Rendered markdown string.

    Example:
        >>> "Integration Strategy" in render_integration_strategy(True, "rebase")
        True
    """
    pr_label = "yes" if branch_pr else "no"
    lines = [
        "## Integration Strategy",
        "",
        "This section describes expected coordination and history semantics.",
        "Atelier does not automate integration.",
        "",
        f"- Pull requests expected: {pr_label}",
        f"- History policy: {branch_history}",
        "",
        "When this workspace's success criteria are met:",
    ]
    if branch_pr:
        lines.extend(
            [
                "- The workspace branch is expected to be pushed to the remote.",
                "- A pull request against the default branch is the expected "
                "integration mechanism.",
                "- Manual review is assumed; integration should not happen "
                "automatically.",
            ]
        )
        if branch_history == "manual":
            lines.append(
                "- The intended merge style is manual (no specific history "
                "behavior is implied)."
            )
        else:
            lines.append(
                f"- The intended merge style is {branch_history}, but review "
                "and human control remain authoritative."
            )
        lines.append(
            "- Integration should wait for an explicit instruction in the thread."
        )
    else:
        lines.append(
            "- Integration is expected to happen directly without a pull request."
        )
        if branch_history == "manual":
            lines.append(
                "- No specific history behavior is implied; use human judgment "
                "for how changes land on the default branch."
            )
        elif branch_history == "squash":
            lines.append(
                "- Workspace changes are expected to be collapsed into a single "
                "commit on the default branch."
            )
        elif branch_history == "merge":
            lines.append(
                "- Workspace changes are expected to be merged with a merge "
                "commit, preserving workspace history."
            )
        elif branch_history == "rebase":
            lines.append(
                "- Workspace commits are expected to be replayed linearly onto "
                "the default branch."
            )
        lines.append(
            "- After integration, the default branch is expected to be pushed."
        )
    return "\n".join(lines)


def render_workspace_agents() -> str:
    """Render ``AGENTS.md`` for a new workspace.

    Returns:
        Workspace ``AGENTS.md`` content.

    Example:
        >>> "Atelier" in render_workspace_agents()
        True
    """
    return workspace_agents_template(prefer_installed=True)


def render_persist(branch_pr: bool, branch_history: str) -> str:
    """Render ``PERSIST.md`` for a new workspace.

    Args:
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).

    Returns:
        Workspace ``PERSIST.md`` content.

    Example:
        >>> "Integration Strategy" in render_persist(True, "manual")
        True
    """
    integration_strategy = render_integration_strategy(branch_pr, branch_history)
    return persist_template().format(integration_strategy=integration_strategy)
