"""Helpers for optional default export of newly created planning beads."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from . import beads, config, external_registry, git, paths
from .external_providers import ExternalProvider, ExternalTicketCreateRequest
from .external_tickets import ExternalTicketRef
from .models import ProjectConfig

OPT_OUT_LABELS = {"ext:no-export", "ext:skip-export"}
OPT_OUT_FIELD_VALUES = {"skip", "no", "false", "off", "manual"}
DEFAULT_RETRY_SCRIPT = "skills/tickets/scripts/auto_export_issue.py"


@dataclass(frozen=True)
class AutoExportContext:
    """Resolved runtime context used for automatic external export."""

    project_config: ProjectConfig
    project_dir: Path
    repo_root: Path
    beads_root: Path


@dataclass(frozen=True)
class AutoExportResult:
    """Result payload for automatic export attempts."""

    status: str
    issue_id: str
    provider: str | None
    message: str
    ticket_id: str | None = None
    retry_command: str | None = None


def resolve_auto_export_context(*, repo_hint: Path | None = None) -> AutoExportContext:
    """Resolve project config and path context for automatic export.

    Args:
        repo_hint: Optional filesystem path used to locate the Git enlistment.
            When omitted, the resolver uses `ATELIER_PROJECT`,
            `ATELIER_WORKSPACE_DIR`, then the current working directory.

    Returns:
        A resolved context containing project config, project data dir,
        enlistment root, and Beads root path.

    Raises:
        RuntimeError: If project config cannot be resolved.
    """
    hint = repo_hint
    if hint is None:
        project_env = os.environ.get("ATELIER_PROJECT", "").strip()
        workspace_env = os.environ.get("ATELIER_WORKSPACE_DIR", "").strip()
        if project_env:
            hint = Path(project_env)
        elif workspace_env:
            hint = Path(workspace_env)
        else:
            hint = Path.cwd()
    repo_root, enlistment_path, _origin_raw, origin = git.resolve_repo_enlistment(hint)
    project_dir = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_dir)
    project_config = config.load_project_config(config_path)
    if project_config is None:
        raise RuntimeError(f"missing project config at {config_path}")
    beads_root = config.resolve_beads_root(project_dir, Path(enlistment_path))
    return AutoExportContext(
        project_config=project_config,
        project_dir=project_dir,
        repo_root=repo_root,
        beads_root=beads_root,
    )


def issue_opted_out(issue: dict[str, object]) -> bool:
    """Return true when a bead explicitly opts out of default export."""
    labels = _issue_labels(issue)
    if labels & OPT_OUT_LABELS:
        return True
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    marker = fields.get("external_export", "").strip().lower()
    return marker in OPT_OUT_FIELD_VALUES


def auto_export_issue(
    issue_id: str,
    *,
    context: AutoExportContext,
    provider_slug: str | None = None,
    force: bool = False,
    retry_script: str = DEFAULT_RETRY_SCRIPT,
) -> AutoExportResult:
    """Export a bead to the active provider when auto-export policy allows.

    Args:
        issue_id: Bead id to export.
        context: Resolved auto-export context.
        provider_slug: Optional explicit provider override.
        force: When true, bypasses the project-level auto-export toggle.
        retry_script: Script path used to format retry instructions.

    Returns:
        Structured result describing exported, skipped, or failed state.
    """
    provider = _resolve_provider(context, provider_slug=provider_slug)
    provider_name = provider.slug if provider else None
    issue = _load_issue(issue_id, context=context)
    if issue is None:
        return AutoExportResult(
            status="failed",
            issue_id=issue_id,
            provider=provider_name,
            message=f"issue not found: {issue_id}",
            retry_command=_retry_command(
                issue_id,
                provider_slug=provider_name,
                context=context,
                retry_script=retry_script,
            ),
        )
    if provider is None:
        return AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=None,
            message="no active external provider configured for export",
        )
    if not force and not bool(context.project_config.project.auto_export_new):
        return AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=provider.slug,
            message="auto-export disabled in project config",
        )
    if not force and issue_opted_out(issue):
        return AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=provider.slug,
            message="bead opted out of auto-export",
        )
    existing = beads.parse_external_tickets(_issue_description(issue))
    if _ticket_for_provider(existing, provider.slug) is not None:
        return AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=provider.slug,
            message="bead already has an external ticket for active provider",
        )

    parent_issue_id = _issue_parent_id(issue)
    parent_ticket: ExternalTicketRef | None = None
    if parent_issue_id:
        parent_issue = _load_issue(parent_issue_id, context=context)
        if parent_issue is not None:
            parent_ticket = _ticket_for_provider(
                beads.parse_external_tickets(_issue_description(parent_issue)),
                provider.slug,
            )

    try:
        title = str(issue.get("title") or "").strip() or issue_id
        body = _ticket_body(issue, parent_issue_id=parent_issue_id, parent_ticket=parent_ticket)
        created_ref = _create_ticket_ref(
            provider,
            issue=issue,
            title=title,
            body=body,
            parent_ticket=parent_ticket,
        )
        exported_ticket = _exported_ticket_ref(created_ref, parent_ticket=parent_ticket)
        updated_tickets = _merge_tickets(existing, exported_ticket)
        beads.update_external_tickets(
            issue_id,
            updated_tickets,
            beads_root=context.beads_root,
            cwd=context.project_dir,
        )
    except Exception as exc:
        retry = _retry_command(
            issue_id,
            provider_slug=provider.slug,
            context=context,
            retry_script=retry_script,
        )
        return AutoExportResult(
            status="failed",
            issue_id=issue_id,
            provider=provider.slug,
            message=str(exc) or f"auto-export failed for {issue_id}",
            retry_command=retry,
        )
    except SystemExit as exc:
        retry = _retry_command(
            issue_id,
            provider_slug=provider.slug,
            context=context,
            retry_script=retry_script,
        )
        return AutoExportResult(
            status="failed",
            issue_id=issue_id,
            provider=provider.slug,
            message=f"auto-export aborted with exit code {exc.code}",
            retry_command=retry,
        )
    return AutoExportResult(
        status="exported",
        issue_id=issue_id,
        provider=provider.slug,
        message=f"exported {issue_id} to {provider.slug}",
        ticket_id=exported_ticket.ticket_id,
    )


def _resolve_provider(
    context: AutoExportContext, *, provider_slug: str | None
) -> ExternalProvider | None:
    contexts = external_registry.resolve_external_providers(
        context.project_config, context.repo_root
    )
    requested = (provider_slug or "").strip().lower() or None
    if requested is None:
        env_provider = os.environ.get("ATELIER_EXTERNAL_PROVIDER", "").strip().lower()
        requested = env_provider or (context.project_config.project.provider or "").strip().lower()
        if not requested:
            if len(contexts) == 1:
                return contexts[0].provider
            return None
    for provider_context in contexts:
        if provider_context.provider.slug == requested:
            return provider_context.provider
    return None


def _load_issue(issue_id: str, *, context: AutoExportContext) -> dict[str, object] | None:
    issues = beads.run_bd_json(
        ["show", issue_id], beads_root=context.beads_root, cwd=context.project_dir
    )
    if not issues:
        return None
    issue = issues[0]
    return issue if isinstance(issue, dict) else None


def _ticket_for_provider(
    tickets: list[ExternalTicketRef],
    provider_slug: str,
) -> ExternalTicketRef | None:
    for ticket in tickets:
        if ticket.provider == provider_slug:
            return ticket
    return None


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    if isinstance(description, str):
        return description
    return ""


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    parent = issue.get("parent")
    if isinstance(parent, str):
        cleaned = parent.strip()
        return cleaned or None
    if isinstance(parent, dict):
        parent_id = parent.get("id")
        if isinstance(parent_id, str):
            cleaned = parent_id.strip()
            return cleaned or None
    return None


def _issue_labels(issue: dict[str, object]) -> set[str]:
    raw_labels = issue.get("labels")
    if not isinstance(raw_labels, list):
        return set()
    return {
        str(label).strip().lower()
        for label in raw_labels
        if isinstance(label, str) and label.strip()
    }


def _parse_description_fields(description: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def _ticket_body(
    issue: dict[str, object],
    *,
    parent_issue_id: str | None,
    parent_ticket: ExternalTicketRef | None,
) -> str | None:
    parts: list[str] = []
    description = _issue_description(issue).strip()
    if description:
        parts.append(description)
    acceptance = issue.get("acceptance_criteria") or issue.get("acceptance")
    if isinstance(acceptance, str):
        text = acceptance.strip()
        if text:
            parts.append(f"Acceptance criteria:\n{text}")
    if parent_ticket:
        parent_ref = f"{parent_ticket.provider}:{parent_ticket.ticket_id}"
        parent_url = parent_ticket.url
        if parent_url:
            parts.append(f"Parent external ticket: {parent_ref} ({parent_url})")
        else:
            parts.append(f"Parent external ticket: {parent_ref}")
    if parent_issue_id:
        parts.append(f"Parent bead: {parent_issue_id}")
    bead_id = str(issue.get("id") or "").strip()
    if bead_id:
        parts.append(f"Local bead: {bead_id}")
    if not parts:
        return None
    return "\n\n".join(parts)


def _create_ticket_ref(
    provider: ExternalProvider,
    *,
    issue: dict[str, object],
    title: str,
    body: str | None,
    parent_ticket: ExternalTicketRef | None,
) -> ExternalTicketRef:
    if parent_ticket and provider.capabilities.supports_children:
        try:
            return provider.create_child_ticket(parent_ticket, title=title, body=body)
        except NotImplementedError:
            pass
    issue_id = str(issue.get("id") or "").strip()
    record = provider.create_ticket(
        ExternalTicketCreateRequest(
            bead_id=issue_id or title,
            title=title,
            body=body,
            labels=_external_labels(issue),
        )
    )
    return record.ref


def _external_labels(issue: dict[str, object]) -> tuple[str, ...]:
    labels = {"atelier"}
    issue_labels = _issue_labels(issue)
    if "at:epic" in issue_labels:
        labels.add("epic")
    if "at:changeset" in issue_labels:
        labels.add("changeset")
    return tuple(sorted(labels))


def _exported_ticket_ref(
    created_ref: ExternalTicketRef,
    *,
    parent_ticket: ExternalTicketRef | None,
) -> ExternalTicketRef:
    relation = "derived" if parent_ticket else "primary"
    return ExternalTicketRef(
        provider=created_ref.provider,
        ticket_id=created_ref.ticket_id,
        url=created_ref.url,
        title=created_ref.title,
        summary=created_ref.summary,
        body=created_ref.body,
        notes=created_ref.notes,
        relation=relation,
        direction="exported",
        sync_mode="export",
        state=created_ref.state,
        raw_state=created_ref.raw_state,
        state_updated_at=created_ref.state_updated_at,
        parent_id=parent_ticket.ticket_id if parent_ticket else None,
        on_close=created_ref.on_close,
        content_updated_at=created_ref.content_updated_at,
        notes_updated_at=created_ref.notes_updated_at,
        last_synced_at=created_ref.last_synced_at,
    )


def _merge_tickets(
    existing: list[ExternalTicketRef],
    created: ExternalTicketRef,
) -> list[ExternalTicketRef]:
    merged: list[ExternalTicketRef] = []
    seen: set[tuple[str, str]] = set()
    for ticket in [*existing, created]:
        key = (ticket.provider, ticket.ticket_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ticket)
    return merged


def _retry_command(
    issue_id: str,
    *,
    provider_slug: str | None,
    context: AutoExportContext,
    retry_script: str,
) -> str:
    parts = [
        "python",
        shlex.quote(retry_script),
        "--issue-id",
        shlex.quote(issue_id),
        "--beads-dir",
        shlex.quote(str(context.beads_root)),
    ]
    if provider_slug:
        parts.extend(["--provider", shlex.quote(provider_slug)])
    return " ".join(parts)
