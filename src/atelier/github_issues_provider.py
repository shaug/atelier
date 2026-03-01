"""GitHub Issues provider implementation for external tickets."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator, Sequence

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
_NOT_FOUND_PATTERN = re.compile(r"(^|\D)404(\D|$)")


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
        supports_children=True,
        supports_state_sync=True,
        supports_close=True,
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
        payload = self._create_issue_payload(request)
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
            with _temporary_text_file(body) as body_file:
                _run([*cmd, "--body-file", str(body_file)])
        else:
            _run(cmd)
        return self.sync_state(ref)

    def create_child_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        title: str,
        body: str | None = None,
        labels: tuple[str, ...] = (),
    ) -> ExternalTicketRef:
        _require_gh()
        create_payload = self._create_issue_payload(
            ExternalTicketCreateRequest(
                bead_id=title,
                title=title,
                body=body,
                labels=labels,
            )
        )
        if not isinstance(create_payload, dict):
            raise RuntimeError("Unexpected gh issue create output")
        created_ref = issue_payload_to_ref(create_payload, parent_id=ref.ticket_id)
        if not created_ref:
            raise RuntimeError("Failed to parse created child issue")
        sub_issue_id = _payload_issue_id(create_payload)
        if sub_issue_id is None:
            raise RuntimeError("Failed to parse created child issue id")
        attach_payload = {"sub_issue_id": sub_issue_id}
        with _temporary_text_file(json.dumps(attach_payload)) as payload_file:
            _run_json(
                [
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{self.repo}/issues/{ref.ticket_id}/sub_issues",
                    "--input",
                    str(payload_file),
                ]
            )
        return created_ref

    def close_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        _require_gh()
        cmd = ["gh", "issue", "close", str(ref.ticket_id), "--repo", self.repo]
        if comment:
            cmd.extend(["--comment", comment])
        _run(cmd)
        return self.sync_state(ref)

    def reopen_ticket(
        self,
        ref: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        _require_gh()
        cmd = ["gh", "issue", "reopen", str(ref.ticket_id), "--repo", self.repo]
        if comment:
            cmd.extend(["--comment", comment])
        _run(cmd)
        return self.sync_state(ref)

    def sync_state(self, ref: ExternalTicketRef) -> ExternalTicketRef:
        if not self.sync_options.include_state:
            return ref
        _require_gh()
        payload = _run_json(["gh", "api", f"repos/{self.repo}/issues/{ref.ticket_id}"])
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected gh issue view output")
        parent_payload = _run_json_allow_not_found(
            ["gh", "api", f"repos/{self.repo}/issues/{ref.ticket_id}/parent"]
        )
        parent_id = _payload_ticket_id(parent_payload) if isinstance(parent_payload, dict) else None
        ticket_ref = issue_payload_to_ref(
            payload,
            sync_options=self.sync_options,
            parent_id=parent_id,
        )
        if not ticket_ref:
            raise RuntimeError("Failed to parse issue state")
        return ticket_ref

    def _create_issue_payload(self, request: ExternalTicketCreateRequest) -> object:
        create_payload: dict[str, object] = {"title": request.title}
        if request.body:
            create_payload["body"] = request.body
        if request.labels:
            create_payload["labels"] = list(request.labels)
        with _temporary_text_file(json.dumps(create_payload)) as payload_file:
            return _run_json(
                [
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{self.repo}/issues",
                    "--input",
                    str(payload_file),
                ]
            )


def issue_payload_to_record(
    payload: dict[str, object],
    *,
    sync_options: ExternalTicketSyncOptions | None = None,
) -> ExternalTicketRecord | None:
    options = sync_options or ExternalTicketSyncOptions()
    ref = issue_payload_to_ref(payload, sync_options=options)
    if not ref:
        return None
    raw_title = payload.get("title")
    title = raw_title if isinstance(raw_title, str) else None
    body = None
    if options.include_body:
        raw_body = payload.get("body")
        body = raw_body if isinstance(raw_body, str) else None
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
    parent_id: str | None = None,
) -> ExternalTicketRef | None:
    options = sync_options or ExternalTicketSyncOptions()
    ticket_id = _payload_ticket_id(payload)
    if ticket_id is None:
        return None
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
    parent_ticket_id = parent_id or _payload_ticket_id(payload.get("parent"))
    return ExternalTicketRef(
        provider="github",
        ticket_id=ticket_id,
        url=url_value,
        state=state,
        raw_state=raw_state_value,
        state_updated_at=state_updated_at,
        content_updated_at=content_updated_at,
        parent_id=parent_ticket_id,
    )


def _payload_ticket_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    number = payload.get("number") or payload.get("id")
    if isinstance(number, int):
        return str(number)
    if isinstance(number, str):
        cleaned = number.strip()
        return cleaned or None
    return None


def _payload_issue_id(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    issue_id = payload.get("id")
    if isinstance(issue_id, int):
        return issue_id
    if isinstance(issue_id, str):
        cleaned = issue_id.strip()
        if cleaned.isdigit():
            return int(cleaned)
    return None


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


def _run_json_allow_not_found(cmd: list[str]) -> object | None:
    try:
        return _run_json(cmd)
    except RuntimeError as exc:
        if _NOT_FOUND_PATTERN.search(str(exc)):
            return None
        raise


@contextmanager
def _temporary_text_file(content: str) -> Iterator[Path]:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)
