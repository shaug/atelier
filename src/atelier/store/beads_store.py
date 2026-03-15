"""Beads-backed implementation of Atelier planning store operations."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from atelier import beads as beads_metadata
from atelier import changesets, lifecycle, messages
from atelier.lib.beads import (
    BeadError,
    Beads,
    CloseIssueRequest,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    ShowIssueRequest,
    UpdateIssueRequest,
)

from .contract import (
    AppendNotesRequest,
    ChangesetQuery,
    ClaimMessageRequest,
    ClearHookRequest,
    CreateMessageRequest,
    DependencyMutation,
    EpicQuery,
    LifecycleTransitionRequest,
    MessageQuery,
    ReadyChangesetQuery,
    SetHookRequest,
    UpdateReviewRequest,
)
from .models import (
    ChangesetBranches,
    ChangesetRecord,
    DependencyRecord,
    EpicDiscoveryParity,
    EpicIdentityViolation,
    EpicRecord,
    HookRecord,
    LifecycleStatus,
    LifecycleTransition,
    MessageDelivery,
    MessageRecord,
    MessageThreadKind,
    ReviewMetadata,
    ReviewState,
    WorkItemKind,
    WorkRef,
)

_DEFAULT_SCAN_LIMIT = 10_000
_MAX_UPDATE_ATTEMPTS = 5
_MESSAGE_LABELS = ("at:message", "at:unread")
_ACTIVE_TOP_LEVEL_DISCOVERY_STATUSES = frozenset(
    {
        LifecycleStatus.OPEN,
        LifecycleStatus.IN_PROGRESS,
        LifecycleStatus.BLOCKED,
    }
)
_REVIEW_STATE_MAP = {
    ReviewState.PUSHED.value: ReviewState.PUSHED,
    ReviewState.DRAFT_PR.value: ReviewState.DRAFT_PR,
    ReviewState.PR_OPEN.value: ReviewState.PR_OPEN,
    ReviewState.IN_REVIEW.value: ReviewState.IN_REVIEW,
    ReviewState.APPROVED.value: ReviewState.APPROVED,
    ReviewState.MERGED.value: ReviewState.MERGED,
    ReviewState.CLOSED.value: ReviewState.CLOSED,
}


def _clean_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _normalized_labels(values: tuple[str, ...]) -> set[str]:
    return {cleaned for value in values if (cleaned := _clean_text(value)) is not None}


def _has_contract_label(labels: set[str], label_name: str) -> bool:
    return label_name in labels or lifecycle.has_namespaced_label(labels, label_name)


def _parent_id(issue: IssueRecord) -> str | None:
    return _clean_text(issue.parent.id) if issue.parent is not None else None


def _canonical_status(issue: IssueRecord) -> LifecycleStatus:
    status = lifecycle.canonical_lifecycle_status(issue.status)
    if status is None:
        raise ValueError(f"issue {issue.id} is missing a canonical lifecycle status")
    try:
        return LifecycleStatus(status)
    except ValueError as exc:
        raise ValueError(f"issue {issue.id} has unsupported lifecycle status {status!r}") from exc


def _review_metadata(issue: IssueRecord) -> ReviewMetadata:
    description = issue.description or ""
    fields = beads_metadata.parse_description_fields(description)
    review = changesets.parse_review_metadata(description)
    pr_number = review.pr_number
    normalized_pr_number = int(pr_number) if pr_number and pr_number.isdigit() else None
    review_state = lifecycle.normalize_review_state(review.pr_state)
    return ReviewMetadata(
        pr_url=review.pr_url,
        pr_number=normalized_pr_number,
        pr_state=_REVIEW_STATE_MAP.get(review_state) if review_state else None,
        review_owner=review.review_owner,
        integrated_sha=_clean_text(fields.get("changeset.integrated_sha")),
    )


def _changeset_branches(issue: IssueRecord) -> ChangesetBranches | None:
    fields = beads_metadata.parse_description_fields(issue.description or "")
    branches = ChangesetBranches(
        root_branch=_clean_text(fields.get("changeset.root_branch")),
        parent_branch=_clean_text(fields.get("changeset.parent_branch")),
        work_branch=_clean_text(fields.get("changeset.work_branch")),
        root_base=_clean_text(fields.get("changeset.root_base")),
        parent_base=_clean_text(fields.get("changeset.parent_base")),
    )
    if all(value is None for value in branches.model_dump().values()):
        return None
    return branches


def _epic_root_branch(issue: IssueRecord) -> str | None:
    fields = beads_metadata.parse_description_fields(issue.description or "")
    return _clean_text(fields.get("workspace.root_branch"))


def _epic_label_for_issue(issue: IssueRecord) -> str:
    prefix, _, _rest = issue.id.partition("-")
    normalized = prefix.strip().lower()
    if normalized:
        return f"{normalized}:epic"
    return "at:epic"


def _normalize_description_field_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _set_description_field(description: str, *, key: str, value: str | None) -> str:
    lines = description.splitlines() if description else []
    updated: list[str] = []
    needle = f"{key}:"
    found = False
    for line in lines:
        if line.strip().startswith(needle):
            if not found:
                replacement = value if value is not None else "null"
                updated.append(f"{key}: {replacement}")
                found = True
            continue
        updated.append(line)
    if not found:
        replacement = value if value is not None else "null"
        updated.append(f"{key}: {replacement}")
    return "\n".join(updated).rstrip("\n") + "\n"


def _apply_description_fields(description: str, *, fields: dict[str, str | None]) -> str:
    updated = description or ""
    for key, value in fields.items():
        updated = _set_description_field(updated, key=key, value=value)
    return updated


def _description_fields_match(
    description: str,
    *,
    fields: dict[str, str | None],
) -> bool:
    parsed = beads_metadata.parse_description_fields(description)
    for key, value in fields.items():
        current = _normalize_description_field_value(parsed.get(key))
        expected = _normalize_description_field_value(value)
        if current != expected:
            return False
    return True


def _append_issue_notes(description: str, *, notes: tuple[str, ...]) -> str:
    base = description.rstrip("\n")
    joined = "\n".join(note for note in notes if note)
    if not joined:
        return description or ""
    if not base:
        return f"{joined}\n"
    if _description_ends_with_notes(description, notes=notes):
        return f"{base}\n"
    return f"{base}\n{joined}\n"


def _description_ends_with_notes(description: str, *, notes: tuple[str, ...]) -> bool:
    if not notes:
        return True
    lines = (description or "").rstrip("\n").splitlines()
    if len(lines) < len(notes):
        return False
    return tuple(lines[-len(notes) :]) == notes


@dataclass
class _ReadState:
    store: "AtelierStore"
    issue_cache: dict[str, IssueRecord] = field(default_factory=dict)
    child_cache: dict[tuple[str, bool], tuple[IssueRecord, ...]] = field(default_factory=dict)
    scan_cache: dict[bool, tuple[IssueRecord, ...]] = field(default_factory=dict)

    async def get_issue(self, issue_id: str) -> IssueRecord:
        if issue_id not in self.issue_cache:
            self.issue_cache[issue_id] = await self.store._show_issue(issue_id)
        return self.issue_cache[issue_id]

    async def scan_issues(
        self,
        *,
        include_closed: bool,
    ) -> tuple[IssueRecord, ...]:
        if include_closed not in self.scan_cache:
            self.scan_cache[include_closed] = await self.store._beads.list(
                ListIssuesRequest(
                    include_closed=include_closed,
                    limit=self.store.scan_limit,
                )
            )
            for issue in self.scan_cache[include_closed]:
                self.issue_cache.setdefault(issue.id, issue)
        return self.scan_cache[include_closed]

    async def child_issues(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> tuple[IssueRecord, ...]:
        key = (parent_id, include_closed)
        if key not in self.child_cache:
            self.child_cache[key] = await self.store._beads.list(
                ListIssuesRequest(
                    parent_id=parent_id,
                    include_closed=include_closed,
                    limit=self.store.scan_limit,
                )
            )
            for issue in self.child_cache[key]:
                self.issue_cache.setdefault(issue.id, issue)
        return self.child_cache[key]

    async def work_children(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> tuple[IssueRecord, ...]:
        children = await self.child_issues(parent_id, include_closed=include_closed)
        return tuple(
            child
            for child in children
            if lifecycle.is_work_issue(
                labels=_normalized_labels(child.labels),
                issue_type=child.type,
            )
        )


class AtelierStore:
    """Concrete Atelier planning store backed by the typed async Beads client.

    Args:
        beads: Typed Beads client used as the only backend boundary.
        scan_limit: Upper bound used when the store must scan issues through the
            Beads list contract because the published client does not expose an
            unlimited listing mode.
    """

    def __init__(self, *, beads: Beads, scan_limit: int = _DEFAULT_SCAN_LIMIT) -> None:
        self._beads = beads
        self.scan_limit = scan_limit

    async def get_epic(self, epic_id: str) -> EpicRecord:
        state = _ReadState(self)
        issue = await state.get_issue(epic_id)
        if not (await self._role(issue, state=state)).is_epic:
            raise LookupError(f"epic not found: {epic_id}")
        return await self._epic_record(issue, state=state)

    async def list_epics(
        self,
        query: EpicQuery = EpicQuery(),
    ) -> tuple[EpicRecord, ...]:
        state = _ReadState(self)
        issues = await state.scan_issues(include_closed=query.include_closed)
        records: list[EpicRecord] = []
        for issue in issues:
            if query.assignee is not None and issue.assignee != query.assignee:
                continue
            if await self._is_indexed_epic(issue, state=state):
                records.append(await self._epic_record(issue, state=state))
        return tuple(records)

    async def epic_discovery_parity(self) -> EpicDiscoveryParity:
        state = _ReadState(self)
        issues = await state.scan_issues(include_closed=True)

        active_top_level: list[IssueRecord] = []
        indexed_active_ids: set[str] = set()
        executable_active_ids: set[str] = set()
        missing_identity: list[EpicIdentityViolation] = []

        for issue in issues:
            labels = _normalized_labels(issue.labels)
            parent_id = _parent_id(issue)
            role = lifecycle.infer_work_role(
                labels=labels,
                issue_type=issue.type,
                parent_id=parent_id,
                has_work_children=False,
            )
            canonical_status = _canonical_status(issue)

            if await self._is_indexed_epic(issue, state=state):
                if canonical_status in _ACTIVE_TOP_LEVEL_DISCOVERY_STATUSES:
                    indexed_active_ids.add(issue.id)

            if not role.is_work or not role.is_epic:
                continue
            if canonical_status not in _ACTIVE_TOP_LEVEL_DISCOVERY_STATUSES:
                continue
            active_top_level.append(issue)

            executable_identity = (
                lifecycle.is_executable_epic_identity(
                    labels=labels,
                    issue_type=issue.type,
                    parent_id=parent_id,
                )
                and lifecycle.normalize_status_value(issue.type) == WorkItemKind.EPIC.value
            )
            if executable_identity:
                executable_active_ids.add(issue.id)
                continue
            missing_identity.append(
                EpicIdentityViolation(
                    issue_id=issue.id,
                    status=canonical_status,
                    issue_type=_clean_text(issue.type),
                    labels=tuple(sorted(labels)),
                    remediation_command=(
                        f"bd update {issue.id} --type epic "
                        f"--add-label {_epic_label_for_issue(issue)}"
                    ),
                )
            )

        return EpicDiscoveryParity(
            active_top_level_work_count=len(active_top_level),
            indexed_active_epic_count=len(indexed_active_ids),
            missing_executable_identity=tuple(
                sorted(missing_identity, key=lambda item: item.issue_id)
            ),
            missing_from_index=tuple(sorted(executable_active_ids - indexed_active_ids)),
        )

    async def get_changeset(self, changeset_id: str) -> ChangesetRecord:
        state = _ReadState(self)
        issue = await state.get_issue(changeset_id)
        if not (await self._role(issue, state=state)).is_changeset:
            raise LookupError(f"changeset not found: {changeset_id}")
        return await self._changeset_record(issue, state=state)

    async def list_changesets(
        self,
        query: ChangesetQuery = ChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        state = _ReadState(self)
        issues = await self._candidate_changesets(query=query, state=state)
        records = [await self._changeset_record(issue, state=state) for issue in issues]
        return tuple(records)

    async def list_ready_changesets(
        self,
        query: ReadyChangesetQuery = ReadyChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        state = _ReadState(self)
        ready: list[ChangesetRecord] = []
        changesets = await self._candidate_changesets(
            query=ChangesetQuery(epic_id=query.epic_id),
            state=state,
        )
        for issue in changesets:
            record = await self._changeset_record(issue, state=state)
            if record.lifecycle not in {
                LifecycleStatus.OPEN,
                LifecycleStatus.IN_PROGRESS,
            }:
                continue
            if any(dependency.satisfied is False for dependency in record.dependencies):
                continue
            ready.append(record)
        return tuple(ready)

    async def list_messages(
        self,
        query: MessageQuery = MessageQuery(),
    ) -> tuple[MessageRecord, ...]:
        state = _ReadState(self)
        issues = await state.scan_issues(include_closed=False)
        records: list[MessageRecord] = []
        for issue in issues:
            if not self._matches_issue_kind(issue, "message"):
                continue
            if query.unread_only and not _has_contract_label(
                _normalized_labels(issue.labels),
                "unread",
            ):
                continue
            record = self._message_record(issue)
            if record is None:
                continue
            if query.thread_id is not None and record.thread_id != query.thread_id:
                continue
            if query.queue is not None and record.queue != query.queue:
                continue
            if query.audience and not set(query.audience).issubset(set(record.audience)):
                continue
            records.append(record)
        return tuple(records)

    async def get_agent_hook(self, agent_id: str) -> HookRecord | None:
        state = _ReadState(self)
        issue = await self._find_agent_issue(agent_id, state=state)
        if issue is None:
            return None
        fields = beads_metadata.parse_description_fields(issue.description or "")
        hooked_epic = _normalize_description_field_value(fields.get("hook_bead"))
        return None if hooked_epic is None else HookRecord(agent_id=agent_id, epic_id=hooked_epic)

    async def add_dependency(self, mutation: DependencyMutation) -> DependencyRecord:
        state = _ReadState(self)
        issue = await state.get_issue(mutation.issue_id)
        if not (await self._role(issue, state=state)).is_work:
            raise ValueError(f"dependency source is not work: {mutation.issue_id}")
        dependency_ids = {dependency.id for dependency in issue.dependencies}
        if mutation.depends_on_id in dependency_ids:
            return await self._dependency_record(
                issue,
                depends_on_id=mutation.depends_on_id,
                requires_integrated_state=mutation.requires_integrated_state,
                state=state,
            )
        await state.get_issue(mutation.depends_on_id)
        updated_issue = await self._beads.add_dependency(
            DependencyMutationRequest(
                issue_id=mutation.issue_id,
                dependency_id=mutation.depends_on_id,
            )
        )
        updated_state = _ReadState(self, issue_cache={updated_issue.id: updated_issue})
        return await self._dependency_record(
            updated_issue,
            depends_on_id=mutation.depends_on_id,
            requires_integrated_state=mutation.requires_integrated_state,
            state=updated_state,
        )

    async def remove_dependency(
        self,
        mutation: DependencyMutation,
    ) -> DependencyRecord | None:
        state = _ReadState(self)
        issue = await state.get_issue(mutation.issue_id)
        dependency_ids = {dependency.id for dependency in issue.dependencies}
        if mutation.depends_on_id not in dependency_ids:
            return None
        removed = await self._dependency_record(
            issue,
            depends_on_id=mutation.depends_on_id,
            requires_integrated_state=mutation.requires_integrated_state,
            state=state,
        )
        updated_issue = await self._beads.remove_dependency(
            DependencyMutationRequest(
                issue_id=mutation.issue_id,
                dependency_id=mutation.depends_on_id,
            )
        )
        if any(
            dependency.id == mutation.depends_on_id for dependency in updated_issue.dependencies
        ):
            raise RuntimeError(f"dependency removal could not be verified for {mutation.issue_id}")
        return removed

    async def create_message(self, request: CreateMessageRequest) -> MessageRecord:
        normalized_metadata = messages.normalize_message_metadata(
            {
                "from": request.sender,
                "delivery": request.delivery.value,
                "thread": request.thread_id,
                "thread_kind": request.thread_kind.value if request.thread_kind else None,
                "audience": list(request.audience),
                "kind": request.kind,
                "blocking": request.blocking,
                "reply_to": request.reply_to,
                "queue": request.queue,
            }
        )
        description = messages.render_message(normalized_metadata, request.body)
        created = await self._beads.create(
            CreateIssueRequest(
                title=request.title,
                type="task",
                description=description,
                labels=_MESSAGE_LABELS,
            )
        )
        verified = await self._show_issue(created.id)
        record = self._message_record(verified)
        if record is None or not _has_contract_label(_normalized_labels(verified.labels), "unread"):
            raise RuntimeError(f"message creation could not be verified for {created.id}")
        return record

    async def claim_message(self, request: ClaimMessageRequest) -> MessageRecord:
        issue = await self._show_issue(request.message_id)
        record = self._message_record(issue)
        if record is None:
            raise LookupError(f"message not found: {request.message_id}")
        if record.queue is None:
            raise ValueError(f"message {request.message_id} is not in a queue")
        if record.claimed_by not in {None, request.claimed_by}:
            raise ValueError(f"message {request.message_id} already claimed by {record.claimed_by}")
        if issue.assignee not in {None, "", request.claimed_by}:
            raise ValueError(f"message {request.message_id} already claimed by another agent")

        claimed_at = dt.datetime.now(tz=dt.timezone.utc).isoformat()

        def build_request(current: IssueRecord) -> UpdateIssueRequest:
            current_record = self._message_record(current)
            if current_record is None:
                raise LookupError(f"message not found: {request.message_id}")
            if current_record.queue is None:
                raise ValueError(f"message {request.message_id} is not in a queue")
            if current_record.claimed_by not in {None, request.claimed_by}:
                raise ValueError(
                    f"message {request.message_id} already claimed by {current_record.claimed_by}"
                )
            if current.assignee not in {None, "", request.claimed_by}:
                raise ValueError(f"message {request.message_id} already claimed by another agent")
            payload = messages.parse_message(current.description or "")
            payload.metadata["claimed_by"] = request.claimed_by
            payload.metadata["claimed_at"] = claimed_at
            description = messages.render_message(payload.metadata, payload.body)
            return UpdateIssueRequest(
                issue_id=current.id,
                description=description,
                status=LifecycleStatus.OPEN.value,
                assignee=request.claimed_by,
            )

        def verify(issue: IssueRecord) -> bool:
            current_record = self._message_record(issue)
            return (
                current_record is not None
                and current_record.claimed_by == request.claimed_by
                and bool(current_record.claimed_at)
                and issue.assignee == request.claimed_by
                and lifecycle.canonical_lifecycle_status(issue.status) == LifecycleStatus.OPEN.value
            )

        updated = await self._update_issue_until_verified(
            request.message_id,
            build_request=build_request,
            verify=verify,
            failure_message=f"concurrent queue claim metadata conflict for {request.message_id}",
        )
        record = self._message_record(updated)
        if record is None:
            raise RuntimeError(f"message claim verification failed for {request.message_id}")
        return record

    async def set_agent_hook(self, request: SetHookRequest) -> HookRecord:
        state = _ReadState(self)
        agent_issue = await self._find_agent_issue(request.agent_id, state=state)
        if agent_issue is None:
            raise LookupError(f"agent issue not found: {request.agent_id}")
        current_fields = beads_metadata.parse_description_fields(agent_issue.description or "")
        current_hook = _normalize_description_field_value(current_fields.get("hook_bead"))
        if (
            request.expected_current_epic_id is not None
            and current_hook != request.expected_current_epic_id
        ):
            raise ValueError(
                f"agent {request.agent_id} hook mismatch: expected "
                f"{request.expected_current_epic_id!r}, got {current_hook!r}"
            )
        if current_hook == request.epic_id:
            return HookRecord(agent_id=request.agent_id, epic_id=request.epic_id)

        def build_request(current: IssueRecord) -> UpdateIssueRequest:
            fields = beads_metadata.parse_description_fields(current.description or "")
            existing = _normalize_description_field_value(fields.get("hook_bead"))
            if (
                request.expected_current_epic_id is not None
                and existing != request.expected_current_epic_id
            ):
                raise ValueError(
                    f"agent {request.agent_id} hook mismatch: expected "
                    f"{request.expected_current_epic_id!r}, got {existing!r}"
                )
            description = _apply_description_fields(
                current.description or "",
                fields={"hook_bead": request.epic_id},
            )
            return UpdateIssueRequest(issue_id=current.id, description=description)

        def verify(issue: IssueRecord) -> bool:
            return _description_fields_match(
                issue.description or "",
                fields={"hook_bead": request.epic_id},
            )

        await self._update_issue_until_verified(
            agent_issue.id,
            build_request=build_request,
            verify=verify,
            failure_message=f"agent hook update could not be verified for {request.agent_id}",
        )
        return HookRecord(agent_id=request.agent_id, epic_id=request.epic_id)

    async def clear_agent_hook(self, request: ClearHookRequest) -> HookRecord | None:
        state = _ReadState(self)
        agent_issue = await self._find_agent_issue(request.agent_id, state=state)
        if agent_issue is None:
            return None
        fields = beads_metadata.parse_description_fields(agent_issue.description or "")
        current_hook = _normalize_description_field_value(fields.get("hook_bead"))
        if current_hook is None:
            return None
        if request.expected_epic_id is not None and current_hook != request.expected_epic_id:
            return None

        def build_request(current: IssueRecord) -> UpdateIssueRequest:
            current_fields = beads_metadata.parse_description_fields(current.description or "")
            existing = _normalize_description_field_value(current_fields.get("hook_bead"))
            if existing is None:
                raise ValueError("agent hook disappeared during clear")
            if request.expected_epic_id is not None and existing != request.expected_epic_id:
                raise ValueError(
                    f"agent {request.agent_id} hook mismatch: expected "
                    f"{request.expected_epic_id!r}, got {existing!r}"
                )
            description = _apply_description_fields(
                current.description or "",
                fields={"hook_bead": None},
            )
            return UpdateIssueRequest(issue_id=current.id, description=description)

        def verify(issue: IssueRecord) -> bool:
            return _description_fields_match(
                issue.description or "",
                fields={"hook_bead": None},
            )

        await self._update_issue_until_verified(
            agent_issue.id,
            build_request=build_request,
            verify=verify,
            failure_message=f"agent hook clear could not be verified for {request.agent_id}",
        )
        return HookRecord(agent_id=request.agent_id, epic_id=current_hook)

    async def update_review(self, request: UpdateReviewRequest) -> ChangesetRecord:
        state = _ReadState(self)
        issue = await state.get_issue(request.changeset_id)
        if not (await self._role(issue, state=state)).is_changeset:
            raise LookupError(f"changeset not found: {request.changeset_id}")
        desired_review = request.review
        existing_review = _review_metadata(issue)
        merged_review = ReviewMetadata(
            pr_url=desired_review.pr_url
            if not request.preserve_existing or desired_review.pr_url is not None
            else existing_review.pr_url,
            pr_number=desired_review.pr_number
            if not request.preserve_existing or desired_review.pr_number is not None
            else existing_review.pr_number,
            pr_state=desired_review.pr_state
            if not request.preserve_existing or desired_review.pr_state is not None
            else existing_review.pr_state,
            review_owner=desired_review.review_owner
            if not request.preserve_existing or desired_review.review_owner is not None
            else existing_review.review_owner,
            integrated_sha=desired_review.integrated_sha
            if not request.preserve_existing or desired_review.integrated_sha is not None
            else existing_review.integrated_sha,
        )
        review_fields = {
            "pr_url": merged_review.pr_url,
            "pr_number": str(merged_review.pr_number)
            if merged_review.pr_number is not None
            else None,
            "pr_state": merged_review.pr_state.value
            if merged_review.pr_state is not None
            else None,
            "review_owner": merged_review.review_owner,
            "changeset.integrated_sha": merged_review.integrated_sha,
        }
        if _description_fields_match(issue.description or "", fields=review_fields):
            return await self._changeset_record(issue, state=state)

        def build_request(current: IssueRecord) -> UpdateIssueRequest:
            description = _apply_description_fields(current.description or "", fields=review_fields)
            return UpdateIssueRequest(issue_id=current.id, description=description)

        def verify(issue: IssueRecord) -> bool:
            return _description_fields_match(issue.description or "", fields=review_fields)

        updated = await self._update_issue_until_verified(
            request.changeset_id,
            build_request=build_request,
            verify=verify,
            failure_message=(
                f"review metadata update could not be verified for {request.changeset_id}"
            ),
        )
        updated_state = _ReadState(self, issue_cache={updated.id: updated})
        return await self._changeset_record(updated, state=updated_state)

    async def append_notes(
        self,
        request: AppendNotesRequest,
    ) -> EpicRecord | ChangesetRecord:
        state = _ReadState(self)
        issue = await state.get_issue(request.issue_id)
        role = await self._role(issue, state=state)
        if role.is_epic and role.parent_id is None:
            issue_kind = WorkItemKind.EPIC
        elif role.is_changeset:
            issue_kind = WorkItemKind.CHANGESET
        else:
            raise ValueError(f"notes append requires work items: {request.issue_id}")

        def build_request(current: IssueRecord) -> UpdateIssueRequest:
            description = _append_issue_notes(current.description or "", notes=request.notes)
            return UpdateIssueRequest(issue_id=current.id, description=description)

        def verify(updated_issue: IssueRecord) -> bool:
            return _description_ends_with_notes(
                updated_issue.description or "", notes=request.notes
            )

        updated = await self._update_issue_until_verified(
            request.issue_id,
            build_request=build_request,
            verify=verify,
            failure_message=f"notes append could not be verified for {request.issue_id}",
        )
        updated_state = _ReadState(self, issue_cache={updated.id: updated})
        if issue_kind is WorkItemKind.EPIC:
            return await self._epic_record(updated, state=updated_state)
        return await self._changeset_record(updated, state=updated_state)

    async def transition_lifecycle(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransition:
        state = _ReadState(self)
        issue = await state.get_issue(request.issue_id)
        issue_kind = await self._transition_issue_kind(issue, state=state)
        current_status = _canonical_status(issue)
        if request.expected_current is not None and current_status is not request.expected_current:
            raise ValueError(
                f"lifecycle mismatch for {request.issue_id}: expected "
                f"{request.expected_current.value!r}, got {current_status.value!r}"
            )
        if current_status is request.target_status:
            return LifecycleTransition(
                issue_id=request.issue_id,
                issue_kind=issue_kind,
                from_status=current_status,
                to_status=request.target_status,
                reason=request.reason,
            )
        if request.target_status is LifecycleStatus.CLOSED:
            updated = await self._beads.close(
                CloseIssueRequest(issue_id=request.issue_id, reason=request.reason)
            )
            if lifecycle.canonical_lifecycle_status(updated.status) != LifecycleStatus.CLOSED.value:
                refreshed = await self._show_issue(request.issue_id)
                if lifecycle.canonical_lifecycle_status(refreshed.status) != "closed":
                    raise RuntimeError(
                        f"lifecycle close could not be verified for {request.issue_id}"
                    )
        else:
            expected_from = request.expected_current

            def build_request(current: IssueRecord) -> UpdateIssueRequest:
                current_value = _canonical_status(current)
                if expected_from is not None and current_value is not expected_from:
                    raise ValueError(
                        f"lifecycle mismatch for {request.issue_id}: expected "
                        f"{expected_from.value!r}, got {current_value.value!r}"
                    )
                return UpdateIssueRequest(
                    issue_id=current.id,
                    status=request.target_status.value,
                )

            def verify(issue: IssueRecord) -> bool:
                return (
                    lifecycle.canonical_lifecycle_status(issue.status)
                    == request.target_status.value
                )

            await self._update_issue_until_verified(
                request.issue_id,
                build_request=build_request,
                verify=verify,
                failure_message=(
                    f"lifecycle transition could not be verified for {request.issue_id}"
                ),
            )
        return LifecycleTransition(
            issue_id=request.issue_id,
            issue_kind=issue_kind,
            from_status=current_status,
            to_status=request.target_status,
            reason=request.reason,
        )

    async def _show_issue(self, issue_id: str) -> IssueRecord:
        try:
            return await self._beads.show(ShowIssueRequest(issue_id=issue_id))
        except KeyError as exc:
            raise LookupError(f"issue not found: {issue_id}") from exc
        except BeadError as exc:
            if "got 0" in str(exc):
                raise LookupError(f"issue not found: {issue_id}") from exc
            raise

    async def _update_issue_until_verified(
        self,
        issue_id: str,
        build_request: Callable[[IssueRecord], UpdateIssueRequest],
        verify: Callable[[IssueRecord], bool],
        failure_message: str,
    ) -> IssueRecord:
        for _attempt in range(_MAX_UPDATE_ATTEMPTS):
            current = await self._show_issue(issue_id)
            if verify(current):
                return current
            request = build_request(current)
            updated = await self._beads.update(request)
            if verify(updated):
                return updated
            refreshed = await self._show_issue(issue_id)
            if verify(refreshed):
                return refreshed
        raise RuntimeError(failure_message)

    async def _role(
        self,
        issue: IssueRecord,
        *,
        state: _ReadState,
    ) -> lifecycle.WorkRoleInference:
        labels = _normalized_labels(issue.labels)
        return lifecycle.infer_work_role(
            labels=labels,
            issue_type=issue.type,
            parent_id=_parent_id(issue),
            has_work_children=bool(await state.work_children(issue.id, include_closed=True)),
        )

    async def _is_indexed_epic(self, issue: IssueRecord, *, state: _ReadState) -> bool:
        role = await self._role(issue, state=state)
        return role.is_epic and _has_contract_label(_normalized_labels(issue.labels), "epic")

    def _matches_issue_kind(self, issue: IssueRecord, kind: str) -> bool:
        labels = _normalized_labels(issue.labels)
        return _has_contract_label(labels, kind) or _clean_text(issue.type) == kind

    def _message_record(self, issue: IssueRecord) -> MessageRecord | None:
        if not self._matches_issue_kind(issue, "message"):
            return None
        contract = messages.parse_message_contract(issue.description or "", assignee=issue.assignee)
        routing = messages.work_thread_routing(issue.model_dump(mode="python", by_alias=True))
        status = lifecycle.canonical_lifecycle_status(issue.status)
        queue_name = _clean_text(contract.metadata.get("queue"))
        if contract.delivery == "work-threaded":
            if contract.thread_kind not in {"changeset", "epic"}:
                return None
            return MessageRecord(
                id=issue.id,
                title=issue.title or issue.id,
                body=contract.body,
                delivery=MessageDelivery.WORK_THREADED,
                status=LifecycleStatus(status) if status else None,
                sender=contract.sender,
                thread_id=contract.thread_id,
                thread_kind=MessageThreadKind(contract.thread_kind),
                audience=tuple(contract.audience),
                kind=contract.kind,
                blocking=contract.blocking,
                reply_to=contract.reply_to,
                queue=queue_name,
                claimed_by=_clean_text(contract.metadata.get("claimed_by")),
                claimed_at=_clean_text(contract.metadata.get("claimed_at")),
                blocking_roles=tuple(routing.blocking_roles),
            )
        if not (routing.audiences or queue_name or _clean_text(issue.assignee)):
            return None
        claimed_by = _clean_text(contract.metadata.get("claimed_by"))
        if queue_name and claimed_by is None:
            claimed_by = _clean_text(issue.assignee)
        return MessageRecord(
            id=issue.id,
            title=issue.title or issue.id,
            body=contract.body,
            delivery=MessageDelivery.COMPATIBILITY_ROUTED,
            status=LifecycleStatus(status) if status else None,
            sender=contract.sender,
            thread_id=contract.thread_id,
            thread_kind=(
                MessageThreadKind(contract.thread_kind)
                if contract.thread_kind in {"changeset", "epic"}
                else None
            ),
            audience=tuple(routing.audiences),
            kind=routing.kind,
            blocking=contract.blocking,
            reply_to=contract.reply_to,
            queue=queue_name,
            claimed_by=claimed_by,
            claimed_at=_clean_text(contract.metadata.get("claimed_at")),
            blocking_roles=tuple(routing.blocking_roles),
        )

    async def _candidate_changesets(
        self,
        *,
        query: ChangesetQuery,
        state: _ReadState,
    ) -> tuple[IssueRecord, ...]:
        if query.epic_id is not None:
            epic = await state.get_issue(query.epic_id)
            if not (await self._role(epic, state=state)).is_epic:
                raise LookupError(f"epic not found: {query.epic_id}")
            issues = await self._descendant_changesets(epic, state=state, include_closed=True)
        else:
            issues = []
            for epic in await state.scan_issues(include_closed=query.include_closed):
                if not await self._is_indexed_epic(epic, state=state):
                    continue
                issues.extend(
                    await self._descendant_changesets(
                        epic,
                        state=state,
                        include_closed=True,
                    )
                )
        filtered: list[IssueRecord] = []
        for issue in issues:
            if query.assignee is not None and issue.assignee != query.assignee:
                continue
            record_status = _canonical_status(issue)
            if not query.include_closed and record_status is LifecycleStatus.CLOSED:
                continue
            if query.lifecycle is not None and record_status is not query.lifecycle:
                continue
            filtered.append(issue)
        return tuple(filtered)

    async def _descendant_changesets(
        self,
        epic: IssueRecord,
        *,
        state: _ReadState,
        include_closed: bool,
    ) -> tuple[IssueRecord, ...]:
        descendants: list[IssueRecord] = []
        seen: set[str] = set()
        queue = [epic.id]
        while queue:
            current_id = queue.pop(0)
            work_children = await state.work_children(
                current_id,
                include_closed=include_closed,
            )
            for issue in work_children:
                if issue.id in seen:
                    continue
                seen.add(issue.id)
                grandchild_work = await state.work_children(
                    issue.id,
                    include_closed=include_closed,
                )
                if not grandchild_work:
                    descendants.append(issue)
                queue.append(issue.id)
        if descendants:
            return tuple(descendants)
        if (await self._role(epic, state=state)).is_changeset:
            return (epic,)
        return ()

    async def _epic_record(self, issue: IssueRecord, *, state: _ReadState) -> EpicRecord:
        descendant_changesets = await self._descendant_changesets(
            issue,
            state=state,
            include_closed=True,
        )
        changesets = tuple(
            WorkRef(id=changeset.id, title=changeset.title, kind=WorkItemKind.CHANGESET)
            for changeset in descendant_changesets
        )
        return EpicRecord(
            id=issue.id,
            title=issue.title or issue.id,
            lifecycle=_canonical_status(issue),
            assignee=issue.assignee,
            root_branch=_epic_root_branch(issue),
            labels=issue.labels,
            changesets=changesets,
            dependencies=await self._dependencies(issue, state=state),
        )

    async def _changeset_record(
        self,
        issue: IssueRecord,
        *,
        state: _ReadState,
    ) -> ChangesetRecord:
        return ChangesetRecord(
            id=issue.id,
            title=issue.title or issue.id,
            lifecycle=_canonical_status(issue),
            epic_id=await self._resolve_epic_id(issue, state=state),
            assignee=issue.assignee,
            labels=issue.labels,
            dependencies=await self._dependencies(issue, state=state),
            branches=_changeset_branches(issue),
            review=_review_metadata(issue),
        )

    async def _dependencies(
        self,
        issue: IssueRecord,
        *,
        state: _ReadState,
    ) -> tuple[DependencyRecord, ...]:
        dependencies: list[DependencyRecord] = []
        for dependency in issue.dependencies:
            dependencies.append(
                await self._dependency_record(
                    issue,
                    depends_on_id=dependency.id,
                    requires_integrated_state=True,
                    state=state,
                )
            )
        return tuple(dependencies)

    async def _dependency_record(
        self,
        issue: IssueRecord,
        *,
        depends_on_id: str,
        requires_integrated_state: bool,
        state: _ReadState,
    ) -> DependencyRecord:
        dependency_issue = await state.get_issue(depends_on_id)
        dependency_work_children = await state.work_children(
            dependency_issue.id,
            include_closed=True,
        )
        dependency_review = _review_metadata(dependency_issue)
        satisfied = lifecycle.dependency_issue_satisfied(
            status=dependency_issue.status,
            labels=_normalized_labels(dependency_issue.labels),
            require_integrated=requires_integrated_state,
            review_state=dependency_review.pr_state.value if dependency_review.pr_state else None,
            issue_type=dependency_issue.type,
            has_work_children=bool(dependency_work_children),
        )
        return DependencyRecord(
            issue_id=issue.id,
            depends_on_id=depends_on_id,
            satisfied=satisfied,
            requires_integrated_state=requires_integrated_state,
            status=_canonical_status(dependency_issue),
        )

    async def _resolve_epic_id(self, issue: IssueRecord, *, state: _ReadState) -> str | None:
        current = issue
        seen: set[str] = set()
        while True:
            if current.id in seen:
                raise ValueError(
                    f"detected cyclic parent chain while resolving epic for {issue.id}"
                )
            seen.add(current.id)
            parent_id = _parent_id(current)
            if parent_id is None:
                return current.id
            current = await state.get_issue(parent_id)

    async def _find_agent_issue(
        self,
        agent_id: str,
        *,
        state: _ReadState,
    ) -> IssueRecord | None:
        try:
            direct = await state.get_issue(agent_id)
        except LookupError:
            direct = None
        if direct is not None and self._matches_issue_kind(direct, "agent"):
            return direct
        candidates = await state.scan_issues(include_closed=True)
        title_matches = [
            issue
            for issue in candidates
            if self._matches_issue_kind(issue, "agent") and (issue.title or "") == agent_id
        ]
        if title_matches:
            return self._prefer_active_issue(title_matches)
        description_matches: list[IssueRecord] = []
        for issue in candidates:
            if not self._matches_issue_kind(issue, "agent"):
                continue
            fields = beads_metadata.parse_description_fields(issue.description or "")
            if _clean_text(fields.get("agent_id")) == agent_id:
                description_matches.append(issue)
        if description_matches:
            return self._prefer_active_issue(description_matches)
        return None

    async def _transition_issue_kind(
        self,
        issue: IssueRecord,
        *,
        state: _ReadState,
    ) -> WorkItemKind:
        role = await self._role(issue, state=state)
        if role.is_epic and role.parent_id is None:
            return WorkItemKind.EPIC
        if role.is_changeset:
            return WorkItemKind.CHANGESET
        raise ValueError(f"lifecycle transitions require work items: {issue.id}")

    def _prefer_active_issue(self, issues: list[IssueRecord]) -> IssueRecord:
        return next(
            (
                issue
                for issue in issues
                if lifecycle.canonical_lifecycle_status(issue.status) != "closed"
            ),
            issues[0],
        )


def build_atelier_store(*, beads: Beads) -> AtelierStore:
    """Build the published Atelier store on top of one Beads backend."""

    return AtelierStore(beads=beads)


__all__ = ["AtelierStore", "build_atelier_store"]
