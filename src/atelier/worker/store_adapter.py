"""Worker-local store adapter for startup, claim, hook, and message flows."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

from .. import beads, changesets, lifecycle, messages
from ..io import die
from ..lib.beads import (
    CreateIssueRequest,
    IssueRecord,
    ListIssuesRequest,
    ShowIssueRequest,
    SubprocessBeadsClient,
    SyncBeadsProtocol,
    UpdateIssueRequest,
    build_sync_beads_client,
)
from ..store import (
    AtelierStore,
    ChangesetQuery,
    ClaimMessageRequest,
    ClearAgentBeadHookRequest,
    CreateMessageRequest,
    LifecycleStatus,
    LifecycleTransitionRequest,
    MarkMessageReadRequest,
    MessageQuery,
    MessageThreadKind,
    ReadyChangesetQuery,
    ReviewMetadata,
    ReviewState,
    SetAgentBeadHookRequest,
    StartupMessageRecord,
    UpdateReviewRequest,
    build_atelier_store,
)
from . import selection as worker_selection

_SHOW_JSON_SUFFIX = ("show",)
_READY_JSON_ARGS = ("ready",)
_LIST_JSON_PREFIX = ("list",)
_EPIC_LABEL_SCAN_LIMIT = 10_000
_AGENT_LABEL_SCAN_LIMIT = 10_000


@dataclass(frozen=True)
class _StoreBundle:
    store: AtelierStore
    sync_client: SyncBeadsProtocol


def _build_async_beads_client(*, beads_root: Path, repo_root: Path) -> SubprocessBeadsClient:
    return SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )


def _build_store_bundle(*, beads_root: Path, repo_root: Path) -> _StoreBundle:
    async_client = _build_async_beads_client(beads_root=beads_root, repo_root=repo_root)
    sync_client = build_sync_beads_client(cwd=repo_root, beads_root=beads_root)
    return _StoreBundle(
        store=build_atelier_store(beads=async_client),
        sync_client=sync_client,
    )


@lru_cache(maxsize=None)
def _cached_bundle(beads_root: str, repo_root: str) -> _StoreBundle:
    return _build_store_bundle(beads_root=Path(beads_root), repo_root=Path(repo_root))


def _bundle(*, beads_root: Path, repo_root: Path) -> _StoreBundle:
    return _cached_bundle(str(beads_root), str(repo_root))


def clear_bundle_cache() -> None:
    """Clear cached store clients for deterministic tests."""

    _cached_bundle.cache_clear()


def _issue_payload(record: IssueRecord) -> dict[str, object]:
    return cast(
        dict[str, object],
        record.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _show_issue(
    *,
    issue_id: str,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object] | None:
    try:
        record = _bundle(beads_root=beads_root, repo_root=repo_root).sync_client.show(
            ShowIssueRequest(issue_id=issue_id)
        )
    except KeyError:
        return None
    return _issue_payload(record)


def show_issue(
    issue_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object] | None:
    """Return one raw issue payload for adapter-local compatibility callers."""

    return _show_issue(issue_id=issue_id, beads_root=beads_root, repo_root=repo_root)


def _store_ids_to_payloads(
    issue_ids: list[str],
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for issue_id in issue_ids:
        payload = _show_issue(issue_id=issue_id, beads_root=beads_root, repo_root=repo_root)
        if payload is not None:
            payloads.append(payload)
    return payloads


def list_epics(
    *,
    beads_root: Path,
    repo_root: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List executable epics via typed label-scoped reads."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    payloads: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for label in beads.issue_label_candidates("epic", beads_root=beads_root):
        records = bundle.sync_client.list(
            ListIssuesRequest(
                labels=(label,),
                include_closed=include_closed,
                limit=_EPIC_LABEL_SCAN_LIMIT,
            )
        )
        if len(records) >= _EPIC_LABEL_SCAN_LIMIT:
            raise RuntimeError(
                "epic label scan reached the configured limit "
                f"({_EPIC_LABEL_SCAN_LIMIT}) for {label!r}"
            )
        for record in records:
            if record.id in seen_ids:
                continue
            seen_ids.add(record.id)
            payloads.append(_issue_payload(record))
    return payloads


def list_descendant_changesets(
    parent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List changesets under one epic through AtelierStore discovery."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    records = asyncio.run(
        bundle.store.list_changesets(
            ChangesetQuery(epic_id=parent_id, include_closed=include_closed)
        )
    )
    return _store_ids_to_payloads(
        [record.id for record in records],
        beads_root=beads_root,
        repo_root=repo_root,
    )


def list_work_children(
    parent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List direct child work items through the worker-local store adapter."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    issues = bundle.sync_client.list(
        ListIssuesRequest(
            parent_id=parent_id,
            include_closed=include_closed,
            limit=bundle.store.scan_limit,
        )
    )
    return [
        _issue_payload(issue)
        for issue in issues
        if lifecycle.is_work_issue(labels=set(issue.labels), issue_type=issue.type)
    ]


def _normalize_review_state(value: str | None) -> ReviewState | None:
    normalized = lifecycle.normalize_review_state(value)
    return None if normalized is None else ReviewState(normalized)


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _normalize_pr_number(value: str | None) -> int | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    return int(normalized)


def update_changeset_review(
    changeset_id: str,
    metadata: changesets.ReviewMetadata,
    *,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object]:
    """Update changeset review metadata through the worker-local store adapter."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    record = asyncio.run(
        bundle.store.update_review(
            UpdateReviewRequest(
                changeset_id=changeset_id,
                review=ReviewMetadata(
                    pr_url=_normalized_text(metadata.pr_url),
                    pr_number=_normalize_pr_number(metadata.pr_number),
                    pr_state=_normalize_review_state(metadata.pr_state),
                    review_owner=_normalized_text(metadata.review_owner),
                ),
            )
        )
    )
    payload = _show_issue(issue_id=record.id, beads_root=beads_root, repo_root=repo_root)
    return payload or cast(
        dict[str, object],
        record.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def update_changeset_integrated_sha(
    changeset_id: str,
    integrated_sha: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object]:
    """Persist integrated SHA metadata through AtelierStore review updates."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    record = asyncio.run(
        bundle.store.update_review(
            UpdateReviewRequest(
                changeset_id=changeset_id,
                preserve_existing=True,
                review=ReviewMetadata(integrated_sha=_normalized_text(integrated_sha)),
            )
        )
    )
    payload = _show_issue(issue_id=record.id, beads_root=beads_root, repo_root=repo_root)
    return payload or cast(
        dict[str, object],
        record.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def mark_issue_in_progress(
    issue_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> beads.ExternalTicketReconcileResult:
    """Restore one issue to in-progress using the store lifecycle contract."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    asyncio.run(
        bundle.store.transition_lifecycle(
            LifecycleTransitionRequest(
                issue_id=issue_id,
                target_status=LifecycleStatus.IN_PROGRESS,
            )
        )
    )
    return beads.reconcile_reopened_issue_exported_github_tickets(
        issue_id,
        beads_root=beads_root,
        cwd=repo_root,
    )


def ready_changesets_global(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[dict[str, object]]:
    """List ready changesets via store-backed readiness discovery."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    records = asyncio.run(bundle.store.list_ready_changesets(ReadyChangesetQuery()))
    return _store_ids_to_payloads(
        [record.id for record in records],
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _find_agent_candidates(
    *,
    label: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
) -> tuple[dict[str, object], ...]:
    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    issues = bundle.sync_client.list(
        ListIssuesRequest(
            labels=(label,),
            title_query=agent_id,
            include_closed=True,
            limit=_AGENT_LABEL_SCAN_LIMIT,
        )
    )
    if len(issues) >= _AGENT_LABEL_SCAN_LIMIT:
        raise RuntimeError(
            "agent label scan reached the configured limit "
            f"({_AGENT_LABEL_SCAN_LIMIT}) for {label!r}"
        )
    return tuple(_issue_payload(issue) for issue in issues)


def find_agent_bead(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object] | None:
    """Find one agent bead via typed client reads and compatibility fields."""

    closed_title_match: dict[str, object] | None = None
    closed_description_match: dict[str, object] | None = None
    for label in beads._agent_label_candidates(beads_root=beads_root):
        issues = _find_agent_candidates(
            label=label,
            agent_id=agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        title_open_matches: list[dict[str, object]] = []
        title_closed_matches: list[dict[str, object]] = []
        description_open_matches: list[dict[str, object]] = []
        description_closed_matches: list[dict[str, object]] = []
        for issue in issues:
            title = issue.get("title")
            description = issue.get("description")
            fields = beads.parse_description_fields(
                description if isinstance(description, str) else ""
            )
            is_closed = lifecycle.canonical_lifecycle_status(issue.get("status")) == "closed"
            if isinstance(title, str) and title == agent_id:
                (title_closed_matches if is_closed else title_open_matches).append(issue)
            if fields.get("agent_id") == agent_id:
                (description_closed_matches if is_closed else description_open_matches).append(
                    issue
                )
        if title_open_matches:
            return sorted(title_open_matches, key=beads._agent_issue_sort_key)[0]
        if title_closed_matches and closed_title_match is None:
            closed_title_match = sorted(title_closed_matches, key=beads._agent_issue_sort_key)[0]
        if description_open_matches:
            return sorted(description_open_matches, key=beads._agent_issue_sort_key)[0]
        if description_closed_matches and closed_description_match is None:
            closed_description_match = sorted(
                description_closed_matches,
                key=beads._agent_issue_sort_key,
            )[0]
    if closed_title_match is not None:
        return closed_title_match
    return closed_description_match


def ensure_agent_bead(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    role: str | None = None,
) -> dict[str, object]:
    """Ensure the worker agent bead exists using typed issue operations."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    existing = find_agent_bead(agent_id, beads_root=beads_root, repo_root=repo_root)
    if existing is not None:
        issue_id = str(existing.get("id") or "").strip()
        if issue_id and lifecycle.canonical_lifecycle_status(existing.get("status")) == "closed":
            bundle.sync_client.update(
                UpdateIssueRequest(issue_id=issue_id, status=LifecycleStatus.OPEN.value)
            )
            refreshed = _show_issue(issue_id=issue_id, beads_root=beads_root, repo_root=repo_root)
            if (
                refreshed is not None
                and lifecycle.canonical_lifecycle_status(refreshed.get("status")) != "closed"
            ):
                return refreshed
            existing = None
        if existing is not None:
            return existing
    description = f"agent_id: {agent_id}\n"
    if role:
        description += f"role_type: {role}\n"
    created = bundle.sync_client.create(
        CreateIssueRequest(
            title=agent_id,
            type="agent",
            description=description,
            labels=(beads.issue_label("agent", beads_root=beads_root),),
        )
    )
    return _issue_payload(created)


def resolve_hooked_epic(
    agent_bead_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    """Resolve the current hook through AtelierStore and verify live ownership."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    hook_id = get_agent_hook(agent_bead_id, beads_root=beads_root, repo_root=repo_root)
    if hook_id is None:
        return None
    epic = _show_issue(issue_id=hook_id, beads_root=beads_root, repo_root=repo_root)
    if epic is None:
        return None
    if lifecycle.is_closed_status(epic.get("status")):
        return None
    assignee = epic.get("assignee")
    if not isinstance(assignee, str) or assignee.strip() != agent_id:
        return None
    return hook_id


def get_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    """Return the current hook id for one agent bead, when present."""

    hook = asyncio.run(
        _bundle(beads_root=beads_root, repo_root=repo_root).store.get_agent_bead_hook(agent_bead_id)
    )
    return None if hook is None else hook.epic_id


def agent_hook_observation(
    agent_issue: dict[str, object],
    *,
    beads_root: Path,
    repo_root: Path,
) -> worker_selection.AgentHookObservation:
    """Return hook lookup diagnostics for stale-assignee reclaim checks."""

    agent_bead_id = str(agent_issue.get("id") or "").strip()
    if not agent_bead_id:
        return worker_selection.AgentHookObservation.unknown("agent_bead_id_missing")
    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    try:
        hook = asyncio.run(bundle.store.get_agent_bead_hook(agent_bead_id))
    except LookupError:
        return worker_selection.AgentHookObservation.unknown("hook_lookup_failed")
    except ValueError:
        return worker_selection.AgentHookObservation.unknown("agent_id_missing")
    if hook is None:
        return worker_selection.AgentHookObservation.absent()
    return worker_selection.AgentHookObservation.present(hook.epic_id)


def _normalize_labels(value: object) -> tuple[str, ...]:
    return tuple(sorted(lifecycle.normalized_labels(value)))


def _claim_complete(
    issue: dict[str, object],
    *,
    agent_id: str,
    beads_root: Path,
) -> bool:
    labels = lifecycle.normalized_labels(issue.get("labels"))
    assignee = str(issue.get("assignee") or "").strip()
    return (
        assignee == agent_id
        and lifecycle.canonical_lifecycle_status(issue.get("status")) == "in_progress"
        and beads.has_issue_label(labels, "hooked", beads_root=beads_root)
    )


def release_epic_assignment(
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    expected_assignee: str | None = None,
    expected_hooked: bool | None = None,
) -> bool:
    """Release epic ownership with bounded verification retries."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    issue = _show_issue(issue_id=epic_id, beads_root=beads_root, repo_root=repo_root)
    if issue is None:
        return False
    labels = lifecycle.normalized_labels(issue.get("labels"))
    assignee = str(issue.get("assignee") or "").strip() or None
    normalized_expected = expected_assignee.strip() if expected_assignee else None
    if normalized_expected is not None and assignee != normalized_expected:
        return False
    if expected_hooked is not None:
        has_hooked = beads.has_issue_label(labels, "hooked", beads_root=beads_root)
        if has_hooked != expected_hooked:
            return False

    desired_labels = tuple(
        label
        for label in _normalize_labels(issue.get("labels"))
        if not beads.has_issue_label({label}, "hooked", beads_root=beads_root)
    )
    desired_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if desired_status not in {"closed", "done"}:
        desired_status = "open"
    updated = bundle.sync_client.update(
        UpdateIssueRequest(
            issue_id=epic_id,
            assignee="",
            status=desired_status,
            labels=desired_labels,
        )
    )
    payload = _issue_payload(updated)
    if str(payload.get("assignee") or "").strip():
        refreshed = _show_issue(issue_id=epic_id, beads_root=beads_root, repo_root=repo_root)
        if refreshed is None:
            return False
        payload = refreshed
    return not str(payload.get("assignee") or "").strip() and not beads.has_issue_label(
        lifecycle.normalized_labels(payload.get("labels")),
        "hooked",
        beads_root=beads_root,
    )


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    allow_takeover_from: str | None = None,
) -> dict[str, object]:
    """Claim one epic while preserving fail-closed lifecycle checks."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    issue = _show_issue(issue_id=epic_id, beads_root=beads_root, repo_root=repo_root)
    if issue is None:
        die(f"epic not found: {epic_id}")
    claimability = lifecycle.evaluate_epic_claimability(
        status=issue.get("status"),
        labels=lifecycle.normalized_labels(issue.get("labels")),
        issue_type=lifecycle.issue_payload_type(issue),
        parent_id=worker_selection.issue_parent_id(issue),
    )
    is_executable = lifecycle.is_executable_epic_identity(
        labels=lifecycle.normalized_labels(issue.get("labels")),
        issue_type=lifecycle.issue_payload_type(issue),
        parent_id=worker_selection.issue_parent_id(issue),
    )
    if is_executable and not claimability.claimable:
        detail = ", ".join(claimability.reasons)
        die(
            f"epic {epic_id} is not claimable under lifecycle contract ({detail}); "
            "require top-level work in open/in_progress status"
        )
    if is_executable and worker_selection.is_planner_agent_id(agent_id):
        die(
            f"epic {epic_id} claim rejected for planner {agent_id}; "
            "planner agents cannot claim executable work"
        )
    existing_assignee = str(issue.get("assignee") or "").strip() or None
    if worker_selection.is_planner_agent_id(existing_assignee) and is_executable:
        die(
            f"epic {epic_id} is assigned to planner {existing_assignee}; "
            "planner agents cannot own executable work"
        )
    if (
        existing_assignee
        and existing_assignee != agent_id
        and existing_assignee != allow_takeover_from
    ):
        die(f"epic {epic_id} already has an assignee")
    if (
        existing_assignee
        and allow_takeover_from
        and existing_assignee == allow_takeover_from
        and existing_assignee != agent_id
        and not release_epic_assignment(
            epic_id,
            beads_root=beads_root,
            repo_root=repo_root,
            expected_assignee=allow_takeover_from,
            expected_hooked=beads.has_issue_label(
                lifecycle.normalized_labels(issue.get("labels")),
                "hooked",
                beads_root=beads_root,
            ),
        )
    ):
        die(f"epic {epic_id} takeover failed; claim ownership changed")

    desired_labels = set(_normalize_labels(issue.get("labels")))
    desired_labels.add(beads.issue_label("hooked", beads_root=beads_root))
    if beads._is_standalone_changeset_without_epic_label(
        issue,
        beads_root=beads_root,
        cwd=repo_root,
    ):
        desired_labels.add(beads.issue_label("epic", beads_root=beads_root))

    updated = bundle.sync_client.update(
        UpdateIssueRequest(
            issue_id=epic_id,
            assignee=agent_id,
            status=LifecycleStatus.IN_PROGRESS.value,
            labels=tuple(sorted(desired_labels)),
        )
    )
    payload = _issue_payload(updated)
    if _claim_complete(payload, agent_id=agent_id, beads_root=beads_root):
        return payload
    refreshed = _show_issue(issue_id=epic_id, beads_root=beads_root, repo_root=repo_root)
    if refreshed is not None and _claim_complete(
        refreshed,
        agent_id=agent_id,
        beads_root=beads_root,
    ):
        return refreshed
    if refreshed is not None and str(refreshed.get("assignee") or "").strip() != agent_id:
        die(f"epic {epic_id} claim failed; already assigned")
    die(
        "epic "
        f"{epic_id} claim failed; expected status=in_progress and label "
        f"{beads.issue_label('hooked', beads_root=beads_root)}"
    )


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Bind an agent bead to an epic through AtelierStore hook mutations."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    asyncio.run(
        bundle.store.set_agent_bead_hook(
            SetAgentBeadHookRequest(agent_bead_id=agent_bead_id, epic_id=epic_id)
        )
    )


def clear_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    expected_hook: str | None = None,
) -> None:
    """Clear an agent hook through AtelierStore hook mutations."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    asyncio.run(
        bundle.store.clear_agent_bead_hook(
            ClearAgentBeadHookRequest(
                agent_bead_id=agent_bead_id,
                expected_epic_id=expected_hook,
            )
        )
    )


def _thread_kind(thread_id: str | None) -> MessageThreadKind | None:
    if thread_id is None:
        return None
    inferred = messages.infer_thread_target(thread_id)
    if inferred == "epic":
        return MessageThreadKind.EPIC
    if inferred == "changeset":
        return MessageThreadKind.CHANGESET
    return None


def create_message(
    *,
    subject: str,
    body: str,
    sender: str,
    thread_id: str | None,
    audience: tuple[str, ...],
    queue: str | None,
    kind: str | None,
    blocking: bool | None,
    reply_to: str | None = None,
    beads_root: Path,
    repo_root: Path,
) -> dict[str, object]:
    """Create a durable coordination message through AtelierStore."""

    if thread_id is None:
        return beads.create_message_bead(
            subject=subject,
            body=body,
            metadata={
                "from": sender,
                "queue": queue,
                "kind": kind,
                "blocking": blocking,
                "audience": list(audience),
                "reply_to": reply_to,
            },
            beads_root=beads_root,
            cwd=repo_root,
        )
    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    record = asyncio.run(
        bundle.store.create_message(
            CreateMessageRequest(
                title=subject,
                body=body,
                sender=sender,
                thread_id=thread_id,
                thread_kind=_thread_kind(thread_id),
                audience=audience,
                kind=kind,
                blocking=blocking,
                reply_to=reply_to,
                queue=queue,
            )
        )
    )
    payload = _show_issue(issue_id=record.id, beads_root=beads_root, repo_root=repo_root)
    return payload or {"id": record.id, "title": record.title}


def _startup_messages(
    *,
    beads_root: Path,
    repo_root: Path,
    queue: str | None = None,
    unread_only: bool = True,
) -> tuple[StartupMessageRecord, ...]:
    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    query = MessageQuery(queue=queue, unread_only=unread_only)
    return asyncio.run(bundle.store.list_startup_messages(query))


def _startup_message_thread_is_terminal(
    record: StartupMessageRecord,
    *,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    """Return whether a startup message belongs to terminal work.

    The worker inbox should fail closed on lookup uncertainty, so only a
    successful thread lookup that proves terminal lifecycle state suppresses
    the message from inbox gating.
    """

    thread_id = record.thread_id
    if thread_id is None:
        return False
    thread_kind = record.thread_kind
    if thread_kind not in {MessageThreadKind.CHANGESET, MessageThreadKind.EPIC}:
        return False
    try:
        issue = _show_issue(
            issue_id=thread_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
    except Exception:
        return False
    if issue is None:
        return False
    return lifecycle.is_closed_status(issue.get("status"))


def list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List worker inbox messages using store-backed audience routing."""

    runtime_role = worker_selection.agent_role(agent_id)
    if runtime_role is None:
        return []
    matches: list[dict[str, object]] = []
    for record in _startup_messages(
        beads_root=beads_root,
        repo_root=repo_root,
        unread_only=unread_only,
    ):
        if _startup_message_thread_is_terminal(
            record,
            beads_root=beads_root,
            repo_root=repo_root,
        ):
            continue
        if record.queue:
            continue
        blocking_roles = record.blocking_roles
        audience = record.audience
        if runtime_role not in set(blocking_roles) | set(audience):
            continue
        matches.append({"id": record.id, "title": record.title})
    return matches


def list_queue_messages(
    *,
    beads_root: Path,
    repo_root: Path,
    queue: str | None = None,
    unclaimed_only: bool = True,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List queued messages using store-native queue claim metadata."""

    matches: list[dict[str, object]] = []
    for record in _startup_messages(
        beads_root=beads_root,
        repo_root=repo_root,
        queue=queue,
        unread_only=unread_only,
    ):
        claimed_by = record.claimed_by
        if unclaimed_only and claimed_by:
            continue
        matches.append(
            {
                "id": record.id,
                "title": record.title,
                "queue": record.queue or "queue",
                "claimed_by": claimed_by,
            }
        )
    return matches


def claim_queue_message(
    message_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    queue: str | None = None,
) -> None:
    """Claim a queued message through store-native message claim semantics."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    asyncio.run(
        bundle.store.claim_message(
            ClaimMessageRequest(message_id=message_id, claimed_by=agent_id, queue=queue)
        )
    )


def mark_message_read(
    message_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Mark a message as read through AtelierStore."""

    bundle = _bundle(beads_root=beads_root, repo_root=repo_root)
    asyncio.run(bundle.store.mark_message_read(MarkMessageReadRequest(message_id=message_id)))


def epic_changeset_summary(
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> beads.ChangesetSummary:
    """Summarize one epic's changesets using store-backed changeset discovery."""

    changesets = list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=True,
    )
    if not changesets:
        work_children = list_work_children(
            epic_id,
            beads_root=beads_root,
            repo_root=repo_root,
            include_closed=True,
        )
        if not work_children:
            issue = show_issue(epic_id, beads_root=beads_root, repo_root=repo_root)
            if issue is not None:
                changesets = [issue]
    return beads.summarize_changesets(changesets)


class WorkerStoreBeadsAdapter:
    """Runtime beads port backed by AtelierStore where supported."""

    def run_bd_command(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if len(args) >= 4 and args[:2] == ["slot", "show"] and "--json" in args:
            hook_id = get_agent_hook(args[2], beads_root=beads_root, repo_root=cwd)
            payload = {"slots": {"hook": hook_id}}
            return subprocess.CompletedProcess(
                args=["bd", *args],
                returncode=0,
                stdout=f"{json.dumps(payload)}\n",
                stderr="",
            )
        return beads.run_bd_command(
            args,
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=allow_failure,
        )

    def run_bd_json(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        if args[:1] == list(_SHOW_JSON_SUFFIX) and len(args) >= 2:
            payload = show_issue(args[1], beads_root=beads_root, repo_root=cwd)
            return [] if payload is None else [payload]
        if tuple(args[:1]) == _READY_JSON_ARGS:
            return ready_changesets_global(beads_root=beads_root, repo_root=cwd)
        if args[:1] == list(_LIST_JSON_PREFIX):
            labels = [
                args[index + 1] for index, value in enumerate(args[:-1]) if value == "--label"
            ]
            if any(
                label in beads.issue_label_candidates("epic", beads_root=beads_root)
                for label in labels
            ):
                include_closed = "--all" in args
                return list_epics(
                    beads_root=beads_root,
                    repo_root=cwd,
                    include_closed=include_closed,
                )
            if any(
                label in beads.issue_label_candidates("message", beads_root=beads_root)
                for label in labels
            ):
                queue = None
                unread_only = any(
                    label in beads.issue_label_candidates("unread", beads_root=beads_root)
                    for label in labels
                )
                payloads = []
                for record in _startup_messages(
                    beads_root=beads_root,
                    repo_root=cwd,
                    queue=queue,
                    unread_only=unread_only,
                ):
                    payload = show_issue(record.id, beads_root=beads_root, repo_root=cwd)
                    if payload is not None:
                        payloads.append(payload)
                return payloads
        return beads.run_bd_json(args, beads_root=beads_root, cwd=cwd)

    def ensure_agent_bead(
        self,
        agent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        role: str,
    ) -> dict[str, object]:
        return ensure_agent_bead(
            agent_id,
            beads_root=beads_root,
            repo_root=cwd,
            role=role,
        )

    def find_agent_bead(
        self,
        agent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object] | None:
        return find_agent_bead(agent_id, beads_root=beads_root, repo_root=cwd)

    def claim_epic(
        self,
        epic_id: str,
        agent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_takeover_from: str | None = None,
    ) -> dict[str, object]:
        return claim_epic(
            epic_id,
            agent_id,
            beads_root=beads_root,
            repo_root=cwd,
            allow_takeover_from=allow_takeover_from,
        )

    def clear_agent_hook(
        self,
        agent_bead_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        expected_hook: str | None = None,
    ) -> None:
        clear_agent_hook(
            agent_bead_id,
            beads_root=beads_root,
            repo_root=cwd,
            expected_hook=expected_hook,
        )

    def extract_workspace_root_branch(self, issue: dict[str, object]) -> str | None:
        return beads.extract_workspace_root_branch(issue)

    def update_workspace_root_branch(
        self,
        epic_id: str,
        root_branch: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_override: bool = False,
    ) -> dict[str, object]:
        return beads.update_workspace_root_branch(
            epic_id,
            root_branch,
            beads_root=beads_root,
            cwd=cwd,
            allow_override=allow_override,
        )

    def update_workspace_parent_branch(
        self,
        epic_id: str,
        parent_branch: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_override: bool = False,
    ) -> dict[str, object]:
        return beads.update_workspace_parent_branch(
            epic_id,
            parent_branch,
            beads_root=beads_root,
            cwd=cwd,
            allow_override=allow_override,
        )

    def set_agent_hook(
        self,
        agent_bead_id: str,
        epic_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        set_agent_hook(agent_bead_id, epic_id, beads_root=beads_root, repo_root=cwd)


__all__ = [
    "WorkerStoreBeadsAdapter",
    "agent_hook_observation",
    "claim_epic",
    "claim_queue_message",
    "clear_agent_hook",
    "clear_bundle_cache",
    "create_message",
    "ensure_agent_bead",
    "epic_changeset_summary",
    "find_agent_bead",
    "get_agent_hook",
    "list_descendant_changesets",
    "list_epics",
    "list_inbox_messages",
    "list_queue_messages",
    "list_work_children",
    "mark_issue_in_progress",
    "mark_message_read",
    "ready_changesets_global",
    "release_epic_assignment",
    "resolve_hooked_epic",
    "set_agent_hook",
    "show_issue",
    "update_changeset_integrated_sha",
    "update_changeset_review",
]
