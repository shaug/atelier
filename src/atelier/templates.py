"""Template loading and rendering helpers."""

from importlib import resources
from pathlib import Path

from . import paths

TEMPLATE_PARTS: tuple[tuple[str, ...], ...] = (
    ("AGENTS.md",),
    ("project", "PROJECT.md"),
    ("workspace", "SUCCESS.md"),
    ("workspace", "SUCCESS.ticket.md"),
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


def persist_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the workspace ``PERSIST.md`` template text.

    Returns:
        Template text.

    Example:
        >>> "PERSIST" in persist_template()
        True
    """
    return read_template(
        "workspace",
        "PERSIST.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


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


def render_publish_instructions(branch_pr: bool, branch_history: str) -> str:
    """Render publishing guidance for a workspace.

    Args:
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).

    Returns:
        Rendered markdown string.
    """
    lines = [
        "- Before publish/persist/finalize, run the required workspace checks "
        "(tests/formatting/linting/etc.) described in PROJECT.md, SUCCESS.md, or "
        "the repo's AGENTS.md. Do not proceed if they fail unless the user "
        "explicitly asks to ignore the failures.",
        '- "publish" means publish only; do not finalize or tag.',
        '- "persist" means save progress to the remote per the publish model '
        "without finalizing.",
        '- "finalize" means ensure the workspace is published first (perform '
        "publishing if needed), then integrate onto the default branch (merge a "
        "PR or rebase/merge as configured), push, and tag only after publishing "
        "is complete.",
    ]
    if branch_pr:
        lines.extend(
            [
                '- When `branch.pr` is true, "persist" means commit and push to the '
                "workspace branch but do not create or update a pull request yet.",
                '- When `branch.pr` is true, "publish" means commit, push, and '
                "create or update the pull request.",
                "- Publishing is complete only after the workspace branch is pushed "
                "and the pull request is created or updated.",
                "- Do not finalize until publishing is complete.",
            ]
        )
    else:
        lines.extend(
            [
                '- When `branch.pr` is false, "persist" means the same thing as '
                '"publish" (commit, update the default branch per the history '
                "policy, and push).",
                "- Publishing is complete only after the default branch has been "
                "updated locally (per the history policy) and pushed to the remote.",
                "- When publishing to the default branch, if the push is rejected "
                "because the default branch moved, update your local default branch "
                "and re-apply the workspace changes according to the history policy "
                f"({branch_history}), then push again.",
                "- Do not finalize until publishing is complete.",
            ]
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
    return workspace_agents_template(prefer_installed_if_modified=True)


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
    publish_instructions = render_publish_instructions(branch_pr, branch_history)
    return persist_template(prefer_installed_if_modified=True).format(
        integration_strategy=integration_strategy,
        publish_instructions=publish_instructions,
    )
