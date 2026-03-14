"""Beads-backed implementation of Atelier graph and discovery reads."""

from __future__ import annotations

from dataclasses import dataclass, field

from atelier import beads as beads_metadata
from atelier import changesets, lifecycle, messages
from atelier.lib.beads import (
    BeadError,
    Beads,
    IssueRecord,
    ListIssuesRequest,
    ShowIssueRequest,
)

from .contract import (
    AtelierStore,
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


@dataclass
class _ReadState:
    store: "_BeadsBackedAtelierStore"
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


class _BeadsBackedAtelierStore(AtelierStore):
    """Concrete `AtelierStore` backed by the typed async Beads client.

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
            contract = messages.parse_message_contract(
                issue.description or "",
                assignee=issue.assignee,
            )
            if contract.delivery != "work-threaded":
                continue
            if contract.thread_kind not in {"changeset", "epic"}:
                continue
            if query.thread_id is not None and contract.thread_id != query.thread_id:
                continue
            queue_name = _clean_text(contract.metadata.get("queue"))
            if query.queue is not None and queue_name != query.queue:
                continue
            audience = tuple(contract.audience)
            if query.audience and not set(query.audience).issubset(audience):
                continue
            records.append(
                MessageRecord(
                    id=issue.id,
                    title=issue.title or issue.id,
                    body=contract.body,
                    delivery=MessageDelivery.WORK_THREADED,
                    status=LifecycleStatus(status)
                    if (status := lifecycle.canonical_lifecycle_status(issue.status))
                    else None,
                    sender=contract.sender,
                    thread_id=contract.thread_id,
                    thread_kind=MessageThreadKind(contract.thread_kind),
                    audience=audience,
                    kind=contract.kind,
                    blocking=contract.blocking,
                    reply_to=contract.reply_to,
                    queue=queue_name,
                    claimed_by=_clean_text(contract.metadata.get("claimed_by")),
                    claimed_at=_clean_text(contract.metadata.get("claimed_at")),
                )
            )
        return tuple(records)

    async def get_agent_hook(self, agent_id: str) -> HookRecord | None:
        state = _ReadState(self)
        issue = await self._find_agent_issue(agent_id, state=state)
        if issue is None:
            return None
        fields = beads_metadata.parse_description_fields(issue.description or "")
        hooked_epic = _clean_text(fields.get("hook_bead"))
        return None if hooked_epic is None else HookRecord(agent_id=agent_id, epic_id=hooked_epic)

    async def add_dependency(self, mutation: DependencyMutation) -> DependencyRecord:
        raise NotImplementedError("dependency mutations are implemented in a later store slice")

    async def remove_dependency(
        self,
        mutation: DependencyMutation,
    ) -> DependencyRecord | None:
        raise NotImplementedError("dependency mutations are implemented in a later store slice")

    async def create_message(self, request: CreateMessageRequest) -> MessageRecord:
        raise NotImplementedError("message mutations are implemented in a later store slice")

    async def claim_message(self, request: ClaimMessageRequest) -> MessageRecord:
        raise NotImplementedError("message mutations are implemented in a later store slice")

    async def set_agent_hook(self, request: SetHookRequest) -> HookRecord:
        raise NotImplementedError("hook mutations are implemented in a later store slice")

    async def clear_agent_hook(self, request: ClearHookRequest) -> HookRecord | None:
        raise NotImplementedError("hook mutations are implemented in a later store slice")

    async def update_review(self, request: UpdateReviewRequest) -> ChangesetRecord:
        raise NotImplementedError("review mutations are implemented in a later store slice")

    async def transition_lifecycle(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransition:
        raise NotImplementedError("lifecycle mutations are implemented in a later store slice")

    async def _show_issue(self, issue_id: str) -> IssueRecord:
        try:
            return await self._beads.show(ShowIssueRequest(issue_id=issue_id))
        except KeyError as exc:
            raise LookupError(f"issue not found: {issue_id}") from exc
        except BeadError as exc:
            if "got 0" in str(exc):
                raise LookupError(f"issue not found: {issue_id}") from exc
            raise

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
            dependency_issue = await state.get_issue(dependency.id)
            dependency_work_children = await state.work_children(
                dependency_issue.id,
                include_closed=True,
            )
            dependency_review = _review_metadata(dependency_issue)
            satisfied = lifecycle.dependency_issue_satisfied(
                status=dependency_issue.status,
                labels=_normalized_labels(dependency_issue.labels),
                require_integrated=True,
                review_state=dependency_review.pr_state.value
                if dependency_review.pr_state is not None
                else None,
                issue_type=dependency_issue.type,
                has_work_children=bool(dependency_work_children),
            )
            dependencies.append(
                DependencyRecord(
                    issue_id=issue.id,
                    depends_on_id=dependency.id,
                    satisfied=satisfied,
                )
            )
        return tuple(dependencies)

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

    return _BeadsBackedAtelierStore(beads=beads)


__all__ = ["build_atelier_store"]
