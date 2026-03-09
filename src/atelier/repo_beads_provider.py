"""Repo-local Beads provider adapter for external tickets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from . import beads, paths
from .external_providers import (
    ExternalProviderCapabilities,
    ExternalTicketCreateRequest,
    ExternalTicketImportRequest,
    ExternalTicketLinkRequest,
    ExternalTicketRecord,
    ExternalTicketSyncOptions,
)
from .external_tickets import ExternalTicketRef, normalize_state
from .lib.beads import (
    CloseIssueRequest,
    CreateIssueRequest,
    IssueRecord,
    ListIssuesRequest,
    ShowIssueRequest,
    SubprocessBeadsClient,
    SyncBeadsClient,
    UpdateIssueRequest,
)


class _SyncBeadsProtocol(Protocol):
    def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]: ...

    def show(self, request: ShowIssueRequest) -> IssueRecord: ...

    def create(self, request: CreateIssueRequest) -> IssueRecord: ...

    def update(self, request: UpdateIssueRequest) -> IssueRecord: ...

    def close(self, request: CloseIssueRequest) -> IssueRecord: ...


def _build_beads_client(
    *,
    repo_root: Path,
    beads_root: Path,
    readonly: bool = False,
) -> _SyncBeadsProtocol:
    global_args: tuple[str, ...] = ("--readonly",) if readonly else ()
    return SyncBeadsClient(
        SubprocessBeadsClient(
            cwd=repo_root,
            beads_root=beads_root,
            env={"BEADS_DIR": str(beads_root)},
            global_args=global_args,
        )
    )


@dataclass(frozen=True)
class RepoBeadsProvider:
    """Provider adapter for repo-local Beads (read-only)."""

    repo_root: Path
    beads_root: Path | None = None
    allow_write: bool = False

    slug: str = "beads"
    display_name: str = "Repo Beads"
    sync_options: ExternalTicketSyncOptions = field(default_factory=ExternalTicketSyncOptions)

    @property
    def capabilities(self) -> ExternalProviderCapabilities:
        return ExternalProviderCapabilities(
            supports_import=True,
            supports_create=self.allow_write,
            supports_link=True,
            supports_set_in_progress=self.allow_write,
            supports_update=self.allow_write,
            supports_children=False,
            supports_state_sync=True,
            supports_close=self.allow_write,
        )

    def import_tickets(
        self, request: ExternalTicketImportRequest
    ) -> Sequence[ExternalTicketRecord]:
        issues = self._client(readonly=True).list(
            ListIssuesRequest(
                include_closed=request.include_closed,
                limit=request.limit,
                title_query=request.query,
            )
        )
        sync_options = request.sync_options or self.sync_options
        records: list[ExternalTicketRecord] = []
        for issue in issues:
            record = _issue_payload_to_record(
                _issue_record_to_payload(issue),
                sync_options=sync_options,
            )
            if record:
                records.append(record)
        return records

    def link_ticket(self, request: ExternalTicketLinkRequest) -> ExternalTicketRecord:
        record = self._client(readonly=True).show(
            ShowIssueRequest(issue_id=request.ticket.ticket_id)
        )
        sync_options = request.sync_options or self.sync_options
        parsed = _issue_payload_to_record(
            _issue_record_to_payload(record), sync_options=sync_options
        )
        if not parsed:
            raise RuntimeError(f"Failed to parse Beads issue: {request.ticket.ticket_id}")
        return parsed

    def create_ticket(self, request: ExternalTicketCreateRequest) -> ExternalTicketRecord:
        if not self.allow_write:
            raise RuntimeError("Repo Beads export disabled (allow_write=false)")
        created = self._client().create(
            CreateIssueRequest(
                title=request.title,
                type=_resolve_issue_type(request.labels),
                description=request.body,
                labels=request.labels,
            )
        )
        record = _issue_payload_to_record(
            _issue_record_to_payload(created),
            sync_options=self.sync_options,
        )
        if not record:
            raise RuntimeError("Failed to parse created Beads issue")
        return record

    def set_in_progress(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        if not self.allow_write:
            raise RuntimeError("Repo Beads export disabled (allow_write=false)")
        self._client().update(UpdateIssueRequest(issue_id=ref.ticket_id, status="in_progress"))
        return self.sync_state(ref)

    def update_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str | None = None,
        body: str | None = None,
    ) -> ExternalTicketRef:
        if not self.allow_write:
            raise RuntimeError("Repo Beads export disabled (allow_write=false)")
        if not title and body is None:
            return ref
        description = None
        if body is not None:
            existing = self._client(readonly=True).show(ShowIssueRequest(issue_id=ref.ticket_id))
            payload = _issue_record_to_payload(existing)
            description = payload.get("description")
            merged = beads.merge_description_preserving_metadata(
                description if isinstance(description, str) else "",
                body,
            )
            description = merged
        self._client().update(
            UpdateIssueRequest(
                issue_id=ref.ticket_id,
                title=title,
                description=description,
            )
        )
        return self.sync_state(ref)

    def create_child_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str,
        body: str | None = None,
        labels: tuple[str, ...] = (),
    ) -> ExternalTicketRef:
        if not self.allow_write:
            raise RuntimeError("Repo Beads export disabled (allow_write=false)")
        del ref
        created = self._client().create(
            CreateIssueRequest(
                title=title,
                type="task",
                description=body,
                labels=labels,
            )
        )
        return ExternalTicketRef(provider="beads", ticket_id=created.id)

    def close_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        del comment  # Not supported by Beads close command.
        if not self.allow_write:
            raise RuntimeError("Repo Beads export disabled (allow_write=false)")
        self._client().close(CloseIssueRequest(issue_id=ref.ticket_id))
        return self.sync_state(ref)

    def sync_state(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        if not self.sync_options.include_state:
            return ref
        payload = _issue_record_to_payload(
            self._client(readonly=True).show(ShowIssueRequest(issue_id=ref.ticket_id))
        )
        refreshed = _issue_payload_to_ref(payload, sync_options=self.sync_options)
        return refreshed or ref

    def _beads_root(self) -> Path:
        beads_root = self.beads_root or (self.repo_root / paths.BEADS_DIRNAME)
        if not beads_root.exists():
            raise RuntimeError(f"missing Beads store at {beads_root}")
        return beads_root

    def _client(self, *, readonly: bool = False) -> _SyncBeadsProtocol:
        return _build_beads_client(
            repo_root=self.repo_root,
            beads_root=self._beads_root(),
            readonly=readonly,
        )


def _issue_record_to_payload(record: IssueRecord) -> dict[str, object]:
    return record.model_dump(mode="json", by_alias=True, exclude_none=True)


def _issue_payload_to_record(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions,
) -> ExternalTicketRecord | None:
    ref = _issue_payload_to_ref(payload, sync_options=sync_options)
    if not ref:
        return None
    raw_title = payload.get("title")
    raw_description = payload.get("description")
    raw_acceptance = payload.get("acceptance_criteria")
    title = raw_title if isinstance(raw_title, str) else None
    description = raw_description if isinstance(raw_description, str) else None
    acceptance = raw_acceptance if isinstance(raw_acceptance, str) else None
    body = None
    if sync_options.include_body:
        body = _format_body(description, acceptance)
    raw_labels = payload.get("labels")
    labels = (
        tuple(label for label in raw_labels if isinstance(label, str) and label)
        if isinstance(raw_labels, list)
        else ()
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


def _resolve_issue_type(labels: Sequence[str]) -> str:
    for label in labels:
        normalized = label.strip().lower()
        if normalized.endswith(":epic") or normalized == "epic":
            return "epic"
        if normalized.endswith(":task") or normalized == "task":
            return "task"
        if normalized.endswith(":bug") or normalized == "bug":
            return "bug"
        if normalized.endswith(":feature") or normalized == "feature":
            return "feature"
        if normalized.endswith(":chore") or normalized == "chore":
            return "chore"
    return "task"
