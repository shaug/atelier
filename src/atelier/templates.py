"""Template loading and rendering helpers."""

from importlib import resources


def _read_template(*parts: str) -> str:
    """Read a bundled template file from the package.

    Args:
        *parts: Path components under ``atelier/templates``.

    Returns:
        Template text.

    Example:
        >>> isinstance(_read_template("project", "AGENTS.md"), str)
        True
    """
    return (
        resources.files("atelier")
        .joinpath("templates")
        .joinpath(*parts)
        .read_text(encoding="utf-8")
    )


def project_agents_template() -> str:
    """Return the project-level ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier" in project_agents_template()
        True
    """
    return _read_template("project", "AGENTS.md")


def project_md_template() -> str:
    """Return the project-level ``PROJECT.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "PROJECT" in project_md_template()
        True
    """
    return _read_template("project", "PROJECT.md")


def workspace_agents_template() -> str:
    """Return the workspace ``AGENTS.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "Atelier Workspace" in workspace_agents_template()
        True
    """
    return _read_template("workspace", "AGENTS.md")


def workspace_md_template() -> str:
    """Return the workspace ``WORKSPACE.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "WORKSPACE" in workspace_md_template()
        True
    """
    return _read_template("workspace", "WORKSPACE.md")


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


def render_workspace_agents(workspace_id: str, integration_strategy: str) -> str:
    """Render ``AGENTS.md`` for a new workspace.

    Args:
        workspace_id: Workspace identifier string.
        integration_strategy: Rendered integration strategy section.

    Returns:
        Workspace ``AGENTS.md`` content with placeholders filled.

    Example:
        >>> "Integration Strategy" in render_workspace_agents("atelier:demo", "## Integration Strategy")
        True
    """
    return workspace_agents_template().format(
        workspace_id=workspace_id,
        integration_strategy=integration_strategy,
    )
