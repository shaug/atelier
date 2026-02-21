"""GitHub Issues provider implementation for external tickets."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Sequence

from .external_providers import (
    ExternalProviderCapabilities,
    ExternalTicketCreateRequest,
    ExternalTicketImportRequest,
    ExternalTicketLinkRequest,
    ExternalTicketRecord,
    ExternalTicketSyncOptions,
)
from .external_tickets import ExternalTicketRef, normalize_state

DEFAULT_IN_PROGRESS_LABEL = "in-progress"


@dataclass(frozen=True)
class GithubIssuesProvider:
    """Provider adapter for GitHub Issues via the gh CLI."""

    repo: str

    slug: str = "github"
    display_name: str = "GitHub Issues"
    sync_options: ExternalTicketSyncOptions = field(default_factory=ExternalTicketSyncOptions)
    capabilities: ExternalProviderCapabilities = ExternalProviderCapabilities(
        supports_import=True,
        supports_create=True,
        supports_link=True,
        supports_set_in_progress=True,
        supports_update=True,
        supports_children=False,
        supports_state_sync=True,
    )

    def import_tickets(
        self, request: ExternalTicketImportRequest
    ) -> Sequence[ExternalTicketRecord]:
        _require_gh()
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self.repo,
            "--json",
            "number,title,url,state,body,labels,updatedAt,stateReason",
            "--state",
            "all" if request.include_closed else "open",
        ]
        if request.limit:
            cmd.extend(["--limit", str(request.limit)])
        if request.query:
            cmd.extend(["--search", request.query])
        payload = _run_json(cmd)
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected gh issue list output")
        sync_options = request.sync_options or self.sync_options
        records: list[ExternalTicketRecord] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            record = issue_payload_to_record(entry, sync_options=sync_options)
            if record:
                records.append(record)
        return records

    def create_ticket(self, request: ExternalTicketCreateRequest) -> ExternalTicketRecord:
        _require_gh()
        cmd = [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{self.repo}/issues",
            "-f",
            f"title={request.title}",
        ]
        if request.body:
            cmd.extend(["-f", f"body={request.body}"])
        for label in request.labels:
            cmd.extend(["-f", f"labels[]={label}"])
        payload = _run_json(cmd)
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected gh issue create output")
        record = issue_payload_to_record(payload)
        if not record:
            raise RuntimeError("Failed to parse created issue")
        return record

    def link_ticket(self, request: ExternalTicketLinkRequest) -> ExternalTicketRecord:
        _require_gh()
        payload = _run_json(["gh", "api", f"repos/{self.repo}/issues/{request.ticket.ticket_id}"])
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected gh issue view output")
        sync_options = request.sync_options or self.sync_options
        record = issue_payload_to_record(payload, sync_options=sync_options)
        if not record:
            raise RuntimeError("Failed to parse linked issue")
        return record

    def set_in_progress(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        _require_gh()
        _run(
            [
                "gh",
                "issue",
                "edit",
                str(ref.ticket_id),
                "--repo",
                self.repo,
                "--add-label",
                DEFAULT_IN_PROGRESS_LABEL,
            ]
        )
        return self.sync_state(ref)

    def update_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str | None = None,
        body: str | None = None,
    ) -> ExternalTicketRef:
        _require_gh()
        if not title and body is None:
            return ref
        cmd = ["gh", "issue", "edit", str(ref.ticket_id), "--repo", self.repo]
        if title:
            cmd.extend(["--title", title])
        if body is not None:
            cmd.extend(["--body", body])
        _run(cmd)
        return self.sync_state(ref)

    def create_child_ticket(
        self, ref: ExternalTicketRef, *, title: str, body: str | None = None
    ) -> ExternalTicketRef:
        raise NotImplementedError("GitHub Issues does not support child tickets")

    def sync_state(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        if not self.sync_options.include_state:
            return ref
        _require_gh()
        payload = _run_json(["gh", "api", f"repos/{self.repo}/issues/{ref.ticket_id}"])
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected gh issue view output")
        ticket_ref = issue_payload_to_ref(payload, sync_options=self.sync_options)
        if not ticket_ref:
            raise RuntimeError("Failed to parse issue state")
        return ticket_ref


def issue_payload_to_record(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions | None = None,
) -> ExternalTicketRecord | None:
    options = sync_options or ExternalTicketSyncOptions()
    ref = issue_payload_to_ref(payload, sync_options=options)
    if not ref:
        return None
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    body = None
    if options.include_body:
        body = payload.get("body") if isinstance(payload.get("body"), str) else None
    labels = tuple(_label_names(payload.get("labels")))
    summary = payload.get("stateReason")
    if not options.include_notes or not isinstance(summary, str):
        summary = None
    return ExternalTicketRecord(
        ref=ref,
        title=title,
        body=body,
        labels=labels,
        summary=summary,
        raw=payload,
    )


def issue_payload_to_ref(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions | None = None,
) -> ExternalTicketRef | None:
    options = sync_options or ExternalTicketSyncOptions()
    number = payload.get("number") or payload.get("id")
    if not isinstance(number, int | str):
        return None
    ticket_id = str(number)
    url = payload.get("url") or payload.get("html_url")
    url_value = url if isinstance(url, str) else None
    raw_state_value = None
    state = None
    state_updated_at = None
    content_updated_at = None
    updated_at = payload.get("updatedAt") or payload.get("updated_at")
    updated_at_value = updated_at if isinstance(updated_at, str) else None
    if options.include_state:
        raw_state = payload.get("stateReason") or payload.get("state")
        raw_state_value = raw_state if isinstance(raw_state, str) else None
        state = normalize_state(payload.get("state")) or "unknown"
        state_updated_at = updated_at_value
    if options.include_body or options.include_notes:
        content_updated_at = updated_at_value
    return ExternalTicketRef(
        provider="github",
        ticket_id=ticket_id,
        url=url_value,
        state=state,
        raw_state=raw_state_value,
        state_updated_at=state_updated_at,
        content_updated_at=content_updated_at,
    )


def _label_names(payload: object) -> list[str]:
    names: list[str] = []
    if not isinstance(payload, list):
        return names
    for entry in payload:
        if isinstance(entry, dict):
            value = entry.get("name")
            if isinstance(value, str) and value:
                names.append(value)
        elif isinstance(entry, str) and entry:
            names.append(entry)
    return names


def _require_gh() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("missing required command: gh")


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"Command failed: {' '.join(cmd)}")
    return result.stdout


def _run_json(cmd: list[str]) -> object:
    output = _run(cmd)
    if not output.strip():
        return None
    return json.loads(output)
