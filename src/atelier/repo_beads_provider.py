"""Repo-local Beads provider adapter for external tickets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import paths
from .beads import run_bd_json
from .external_providers import (
    ExternalProviderCapabilities,
    ExternalTicketCreateRequest,
    ExternalTicketImportRequest,
    ExternalTicketLinkRequest,
    ExternalTicketRecord,
    ExternalTicketSyncOptions,
)
from .external_tickets import ExternalTicketRef, normalize_state


@dataclass(frozen=True)
class RepoBeadsProvider:
    """Provider adapter for repo-local Beads (read-only)."""

    repo_root: Path
    beads_root: Path | None = None

    slug: str = "beads"
    display_name: str = "Repo Beads"
    sync_options: ExternalTicketSyncOptions = field(
        default_factory=ExternalTicketSyncOptions
    )
    capabilities: ExternalProviderCapabilities = ExternalProviderCapabilities(
        supports_import=True,
        supports_create=False,
        supports_link=True,
        supports_set_in_progress=False,
        supports_update=False,
        supports_children=False,
        supports_state_sync=True,
    )

    def import_tickets(
        self, request: ExternalTicketImportRequest
    ) -> Sequence[ExternalTicketRecord]:
        args = ["--readonly", "list"]
        if request.include_closed:
            args.append("--all")
        if request.limit:
            args.extend(["--limit", str(request.limit)])
        if request.query:
            args.extend(["--title-contains", request.query])
        payload = self._run_bd(args)
        sync_options = request.sync_options or self.sync_options
        records: list[ExternalTicketRecord] = []
        for entry in payload:
            record = _issue_payload_to_record(entry, sync_options=sync_options)
            if record:
                records.append(record)
        return records

    def link_ticket(self, request: ExternalTicketLinkRequest) -> ExternalTicketRecord:
        payload = self._run_bd(["--readonly", "show", request.ticket.ticket_id])
        if not payload:
            raise RuntimeError(f"Beads issue not found: {request.ticket.ticket_id}")
        sync_options = request.sync_options or self.sync_options
        record = _issue_payload_to_record(payload[0], sync_options=sync_options)
        if not record:
            raise RuntimeError(
                f"Failed to parse Beads issue: {request.ticket.ticket_id}"
            )
        return record

    def create_ticket(
        self, request: ExternalTicketCreateRequest
    ) -> ExternalTicketRecord:
        raise NotImplementedError("Repo Beads provider is read-only")

    def set_in_progress(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        raise NotImplementedError("Repo Beads provider is read-only")

    def update_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str | None = None,
        body: str | None = None,
    ) -> ExternalTicketRef:
        raise NotImplementedError("Repo Beads provider is read-only")

    def create_child_ticket(
        self, ref: ExternalTicketRef, *, title: str, body: str | None = None
    ) -> ExternalTicketRef:
        raise NotImplementedError("Repo Beads provider is read-only")

    def sync_state(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        if not self.sync_options.include_state:
            return ref
        payload = self._run_bd(["--readonly", "show", ref.ticket_id])
        if not payload:
            return ref
        refreshed = _issue_payload_to_ref(payload[0], sync_options=self.sync_options)
        return refreshed or ref

    def _run_bd(self, args: list[str]) -> list[dict[str, object]]:
        beads_root = self.beads_root or (self.repo_root / paths.BEADS_DIRNAME)
        if not beads_root.exists():
            raise RuntimeError(f"missing Beads store at {beads_root}")
        return run_bd_json(args, beads_root=beads_root, cwd=self.repo_root)


def _issue_payload_to_record(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions,
) -> ExternalTicketRecord | None:
    ref = _issue_payload_to_ref(payload, sync_options=sync_options)
    if not ref:
        return None
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    description = (
        payload.get("description")
        if isinstance(payload.get("description"), str)
        else None
    )
    acceptance = (
        payload.get("acceptance_criteria")
        if isinstance(payload.get("acceptance_criteria"), str)
        else None
    )
    body = None
    if sync_options.include_body:
        body = _format_body(description, acceptance)
    labels = tuple(
        label for label in payload.get("labels", []) if isinstance(label, str) and label
    )
    return ExternalTicketRecord(
        ref=ref,
        title=title,
        body=body,
        labels=labels,
        raw=payload,
    )


def _issue_payload_to_ref(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions,
) -> ExternalTicketRef | None:
    issue_id = payload.get("id")
    if not isinstance(issue_id, str) or not issue_id:
        return None
    raw_state = payload.get("status")
    raw_state_value = raw_state if isinstance(raw_state, str) else None
    updated_at = payload.get("updated_at")
    updated_at_value = updated_at if isinstance(updated_at, str) else None
    state = None
    state_updated_at = None
    content_updated_at = None
    notes_updated_at = None
    if sync_options.include_state:
        state = normalize_state(raw_state_value) or "unknown"
        state_updated_at = updated_at_value
    if sync_options.include_body:
        content_updated_at = updated_at_value
    if sync_options.include_notes:
        notes_updated_at = updated_at_value
    return ExternalTicketRef(
        provider="beads",
        ticket_id=issue_id,
        state=state,
        raw_state=raw_state_value,
        state_updated_at=state_updated_at,
        content_updated_at=content_updated_at,
        notes_updated_at=notes_updated_at,
    )


def _format_body(description: str | None, acceptance: str | None) -> str | None:
    parts: list[str] = []
    if description:
        parts.append(description.strip())
    if acceptance:
        parts.append("Acceptance criteria:\n" + acceptance.strip())
    if not parts:
        return None
    return "\n\n".join(parts)
