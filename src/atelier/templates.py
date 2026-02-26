"""Template loading and rendering helpers."""

import json
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import paths

TEMPLATE_PARTS: tuple[tuple[str, ...], ...] = (
    ("agent", "AGENTS.md"),
    ("AGENTS.planner.md.tmpl",),
    ("AGENTS.worker.md.tmpl",),
)


@dataclass(frozen=True)
class TemplateReadResult:
    """Template text plus source/diagnostics for fallback-aware callers.

    Attributes:
        text: Template content.
        source: Source identifier used to return template text.
        attempts: Ordered diagnostics describing lookup attempts.
    """

    text: str
    source: str
    attempts: tuple[str, ...]


class TemplateReadError(RuntimeError):
    """Raised when no readable template source can be resolved."""

    def __init__(self, *, template: str, attempts: tuple[str, ...]) -> None:
        self.template = template
        self.attempts = attempts
        summary = "; ".join(attempts) if attempts else "no lookup attempts recorded"
        super().__init__(f"template_read_failed[{template}]: {summary}")


def _read_template(*parts: str) -> str:
    """Read a bundled template file from the package.

    Args:
        *parts: Path components under ``atelier/templates``.

    Returns:
        Template text.

    Example:
        >>> isinstance(_read_template("agent", "AGENTS.md"), str)
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


def _packaged_template_path(*parts: str) -> str:
    return str(resources.files("atelier").joinpath("templates").joinpath(*parts))


def _runtime_distribution_template_roots() -> tuple[tuple[str, Path], ...]:
    """Return stable package-template roots from the active runtime distribution."""
    try:
        dist = metadata.distribution("atelier")
    except metadata.PackageNotFoundError:
        return ()

    roots: list[tuple[str, Path]] = []
    locate_root = Path(str(dist.locate_file("atelier/templates")))
    if locate_root.is_dir():
        roots.append(("runtime_distribution_locate_file", locate_root))

    direct_url = dist.read_text("direct_url.json")
    if direct_url:
        try:
            payload = json.loads(direct_url)
        except json.JSONDecodeError:
            payload = {}
        source_url = payload.get("url") if isinstance(payload, dict) else None
        if isinstance(source_url, str):
            parsed = urlparse(source_url)
            if parsed.scheme == "file":
                source_path = Path(unquote(parsed.path))
                for candidate in (
                    source_path / "src" / "atelier" / "templates",
                    source_path / "atelier" / "templates",
                ):
                    if candidate.is_dir():
                        roots.append(("runtime_distribution_direct_url", candidate))

    deduped: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for origin, root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        deduped.append((origin, root))
        seen.add(key)
    return tuple(deduped)


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


def read_template_result(
    *parts: str,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> TemplateReadResult:
    """Read template text and return detailed source diagnostics.

    Args:
        *parts: Path components under ``atelier/templates``.
        prefer_installed: When true, prefer the installed cache when readable.
        prefer_installed_if_modified: When true, prefer installed cache only if
            it differs from packaged defaults, while still falling back
            deterministically when packaged defaults are unavailable.

    Returns:
        Source diagnostics with template text.

    Raises:
        TemplateReadError: If no readable source can be resolved.
    """
    attempts: list[str] = []
    installed_path = _installed_template_path(*parts)

    def load_installed() -> str | None:
        if not installed_path.exists():
            attempts.append(f"installed cache missing: {installed_path}")
            return None
        try:
            text = installed_path.read_text(encoding="utf-8")
        except OSError as exc:
            attempts.append(
                f"installed cache unreadable: {installed_path} ({type(exc).__name__}: {exc})"
            )
            return None
        attempts.append(f"installed cache loaded: {installed_path}")
        return text

    def load_packaged() -> str | None:
        runtime_packaged_path = _packaged_template_path(*parts)
        try:
            text = _read_template(*parts)
        except OSError as exc:
            attempts.append(
                "packaged default unreadable: "
                f"{runtime_packaged_path} [origin=runtime_package_resources] "
                f"({type(exc).__name__}: {exc})"
            )
        else:
            attempts.append(
                "packaged default loaded: "
                f"{runtime_packaged_path} [origin=runtime_package_resources]"
            )
            return text

        seen_packaged_paths = {runtime_packaged_path}
        for origin, templates_root in _runtime_distribution_template_roots():
            candidate_path = templates_root.joinpath(*parts)
            candidate_path_str = str(candidate_path)
            if candidate_path_str in seen_packaged_paths:
                continue
            seen_packaged_paths.add(candidate_path_str)
            try:
                text = candidate_path.read_text(encoding="utf-8")
            except OSError as exc:
                attempts.append(
                    "packaged default unreadable: "
                    f"{candidate_path} [origin={origin}] "
                    f"({type(exc).__name__}: {exc})"
                )
                continue
            attempts.append(f"packaged default loaded: {candidate_path} [origin={origin}]")
            return text
        return None

    selected_source = "packaged_default"
    selected_text: str | None = None

    if prefer_installed:
        installed_text = load_installed()
        if installed_text is not None:
            selected_text = installed_text
            selected_source = "installed_cache"
        else:
            selected_text = load_packaged()
            selected_source = "packaged_default"
    elif prefer_installed_if_modified:
        installed_text = load_installed()
        if installed_text is not None:
            packaged_text = load_packaged()
            if packaged_text is None:
                selected_text = installed_text
                selected_source = "installed_cache_fallback"
                attempts.append(
                    "selected source: installed cache fallback because packaged default "
                    "was unavailable"
                )
            elif installed_text != packaged_text:
                selected_text = installed_text
                selected_source = "installed_cache_modified"
                attempts.append(
                    "selected source: installed cache because content differs from packaged default"
                )
            else:
                selected_text = packaged_text
                selected_source = "packaged_default"
                attempts.append(
                    "selected source: packaged default because installed cache "
                    "matches packaged default"
                )
        else:
            selected_text = load_packaged()
            selected_source = "packaged_default"
    else:
        selected_text = load_packaged()
        selected_source = "packaged_default"

    if selected_text is None:
        raise TemplateReadError(template="/".join(parts), attempts=tuple(attempts))

    return TemplateReadResult(
        text=selected_text,
        source=selected_source,
        attempts=tuple(attempts),
    )


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
    return read_template_result(
        *parts,
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    ).text


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


def agent_home_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the canonical agent home ``AGENTS.md`` template text."""
    return read_template(
        "agent",
        "AGENTS.md",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def planner_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the planner AGENTS template text."""
    return read_template(
        "AGENTS.planner.md.tmpl",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )


def worker_template(
    *,
    prefer_installed: bool = False,
    prefer_installed_if_modified: bool = False,
) -> str:
    """Return the worker AGENTS template text."""
    return read_template(
        "AGENTS.worker.md.tmpl",
        prefer_installed=prefer_installed,
        prefer_installed_if_modified=prefer_installed_if_modified,
    )
