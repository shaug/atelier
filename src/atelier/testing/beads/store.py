"""In-memory issue state and mutation semantics for Beads tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from re import Pattern, compile
import threading

from atelier import changeset_fields, lifecycle
from atelier.lib.beads import IssueRecord

_NUMERIC_ID_PATTERN: Pattern[str] = compile(r"^(?P<prefix>[a-z][a-z0-9_-]*)-(?P<value>\d+)$")
UNSET_UPDATE_FIELD = object()


def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return tuple(result)


def _timestamp_for_event(value: int) -> str:
    normalized = max(0, value) % 86400
    hours, remainder = divmod(normalized, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"2025-01-01T{hours:02d}:{minutes:02d}:{seconds:02d}Z"


def _issue_ref(issue_id: str, *, title: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"id": issue_id}
    if title is not None:
        payload["title"] = title
    return payload


def _issue_ref_for(
    issues: Mapping[str, "StoredIssue"],
    issue_id: str,
) -> dict[str, object]:
    issue = issues.get(issue_id)
    return _issue_ref(issue_id, title=issue.title if issue is not None else None)


@dataclass
class StoredIssue:
    """Internal mutable issue state used by the in-memory Beads store."""

    id: str
    title: str
    issue_type: str
    status: str
    labels: tuple[str, ...] = ()
    parent_id: str | None = None
    dependency_ids: tuple[str, ...] = ()
    child_ids: tuple[str, ...] = ()
    description: str | None = None
    design: str | None = None
    acceptance_criteria: str | None = None
    assignee: str | None = None
    owner: str | None = None
    priority: int | None = None
    estimate: int | None = None
    extra_fields: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "StoredIssue":
        """Build internal state from a JSON-compatible issue payload."""

        issue = IssueRecord.model_validate(payload)
        return cls(
            id=issue.id,
            title=issue.title or issue.id,
            issue_type=issue.type or "task",
            status=issue.status or "open",
            labels=tuple(issue.labels),
            parent_id=issue.parent.id if issue.parent else None,
            dependency_ids=tuple(reference.id for reference in issue.dependencies),
            child_ids=tuple(reference.id for reference in issue.children),
            description=issue.description,
            design=issue.design,
            acceptance_criteria=issue.acceptance_criteria,
            assignee=issue.assignee,
            owner=issue.owner,
            priority=issue.priority,
            estimate=issue.estimate,
            extra_fields=issue.extra_fields,
        )


class InMemoryIssueStore:
    """Stateful in-memory issue store for Beads command semantics.

    Args:
        issues: Initial issue payloads to seed into the store.
        prefix: Prefix used for generated numeric ids.
        slots: Optional per-issue slot state keyed by issue id.
    """

    def __init__(
        self,
        *,
        issues: Iterable[Mapping[str, object]] = (),
        prefix: str = "at",
        slots: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._prefix = prefix.strip() or "at"
        self._issues: dict[str, StoredIssue] = {}
        self._order: list[str] = []
        self._slots: dict[str, dict[str, str]] = {
            issue_id: _clean_slot_map(slot_map)
            for issue_id, slot_map in (slots or {}).items()
        }
        self._next_numeric_id = 1
        self._event_counter = 0
        self._lock = threading.RLock()
        for payload in issues:
            self._seed_issue(payload)
        self._repair_parent_child_links()

    def show(self, issue_id: str) -> dict[str, object]:
        """Return one issue payload or raise ``KeyError`` when missing."""

        with self._lock:
            return self._export_issue(self._require_issue(issue_id).id)

    def list(
        self,
        *,
        parent_id: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        title_query: str | None = None,
        title: str | None = None,
        labels: tuple[str, ...] = (),
        include_closed: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Return issues filtered with the current in-memory list semantics."""

        with self._lock:
            title_filter = title_query.lower() if title_query else None
            status_filter = lifecycle.canonical_lifecycle_status(status)
            requested_labels = _dedupe_strings(labels)
            items: list[dict[str, object]] = []
            for issue_id in self._order:
                issue = self._issues[issue_id]
                issue_status = lifecycle.canonical_lifecycle_status(issue.status)
                if parent_id is not None and issue.parent_id != parent_id:
                    continue
                if status_filter is not None and issue_status != status_filter:
                    continue
                if status_filter is None and not include_closed and issue_status == "closed":
                    continue
                if assignee is not None and (issue.assignee or "") != assignee:
                    continue
                if title is not None and issue.title != title:
                    continue
                if title_filter is not None and title_filter not in issue.title.lower():
                    continue
                if requested_labels and not set(requested_labels).issubset(issue.labels):
                    continue
                items.append(self._export_issue(issue_id))
            if limit is None or limit == 0:
                return items
            return items[: max(0, limit)]

    def ready(self, *, parent_id: str | None = None) -> list[dict[str, object]]:
        """Return runnable leaf work beads with satisfied dependencies."""

        with self._lock:
            ready_items: list[dict[str, object]] = []
            for issue_id in self._order:
                issue = self._issues[issue_id]
                if parent_id is not None and issue.parent_id != parent_id:
                    continue
                evaluation = lifecycle.evaluate_runnable_leaf(
                    status=issue.status,
                    labels=set(issue.labels),
                    issue_type=issue.issue_type,
                    parent_id=issue.parent_id,
                    has_work_children=self._has_work_children(issue_id),
                    dependencies_satisfied=self._dependencies_satisfied(issue),
                )
                if evaluation.runnable:
                    ready_items.append(self._export_issue(issue_id))
            return ready_items

    def create(
        self,
        *,
        title: str,
        issue_type: str,
        description: str | None = None,
        design: str | None = None,
        acceptance_criteria: str | None = None,
        assignee: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        estimate: int | None = None,
        labels: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Create and return a new open issue."""

        with self._lock:
            if parent_id is not None:
                self._require_issue(parent_id)
            issue_id = self._allocate_issue_id()
            timestamp = self._next_timestamp()
            stored = StoredIssue(
                id=issue_id,
                title=title,
                issue_type=issue_type,
                status="open",
                labels=_dedupe_strings(labels),
                parent_id=parent_id,
                description=description,
                design=design,
                acceptance_criteria=acceptance_criteria,
                assignee=assignee,
                priority=priority,
                estimate=estimate,
                extra_fields={"created_at": timestamp, "updated_at": timestamp, "metadata": {}},
            )
            self._issues[issue_id] = stored
            self._order.append(issue_id)
            if parent_id is not None:
                self._append_child(parent_id, issue_id)
            return self._export_issue(issue_id)

    def update(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        design: str | None = None,
        acceptance_criteria: str | None = None,
        status: str | None = None,
        assignee: str | object = UNSET_UPDATE_FIELD,
        priority: int | None = None,
        estimate: int | None = None,
        labels: tuple[str, ...] | None = None,
        add_labels: tuple[str, ...] = (),
        remove_labels: tuple[str, ...] = (),
        append_notes: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Update an issue and return the new payload."""

        with self._lock:
            issue = self._require_issue(issue_id)
            if title is not None:
                issue.title = title
            if description is not None:
                issue.description = description
            if design is not None:
                issue.design = design
            if acceptance_criteria is not None:
                issue.acceptance_criteria = acceptance_criteria
            if status is not None:
                issue.status = status
            if assignee is not UNSET_UPDATE_FIELD:
                issue.assignee = _clean_optional_string(assignee)
            if priority is not None:
                issue.priority = priority
            if estimate is not None:
                issue.estimate = estimate
            if labels is not None:
                issue.labels = _dedupe_strings(labels)
            if add_labels:
                issue.labels = _dedupe_strings((*issue.labels, *add_labels))
            if remove_labels:
                removed = set(_dedupe_strings(remove_labels))
                issue.labels = tuple(label for label in issue.labels if label not in removed)
            if append_notes:
                issue.description = _append_issue_notes(issue.description, append_notes)
            issue.extra_fields["updated_at"] = self._next_timestamp()
            return self._export_issue(issue_id)

    def claim(self, issue_id: str, *, actor: str) -> dict[str, object]:
        """Claim an issue for one actor while preserving single-owner semantics."""

        normalized_actor = actor.strip()
        if not normalized_actor:
            raise ValueError("claim requires an actor")
        with self._lock:
            issue = self._require_issue(issue_id)
            if issue.assignee not in {None, normalized_actor}:
                raise ValueError(f"issue {issue_id} already has an assignee")
            issue.assignee = normalized_actor
            issue.extra_fields["updated_at"] = self._next_timestamp()
            return self._export_issue(issue_id)

    def close(self, issue_id: str, *, reason: str | None = None) -> dict[str, object]:
        """Close an issue while preserving existing graph relationships."""

        with self._lock:
            issue = self._require_issue(issue_id)
            issue.status = "closed"
            issue.extra_fields["updated_at"] = self._next_timestamp()
            if reason is not None:
                issue.extra_fields["close_reason"] = reason
            return self._export_issue(issue_id)

    def show_slots(self, issue_id: str) -> dict[str, str]:
        """Return the slot mapping for one issue."""

        with self._lock:
            return dict(self._slots.get(issue_id, {}))

    def set_slot(self, issue_id: str, slot_name: str, slot_value: str) -> None:
        """Persist one slot value for one issue."""

        with self._lock:
            issue_slots = self._slots.setdefault(issue_id, {})
            issue_slots[slot_name] = slot_value

    def clear_slot(self, issue_id: str, slot_name: str) -> None:
        """Clear one slot value for one issue."""

        with self._lock:
            issue_slots = self._slots.get(issue_id)
            if issue_slots is None:
                return
            issue_slots.pop(slot_name, None)
            if not issue_slots:
                self._slots.pop(issue_id, None)

    def _seed_issue(self, payload: Mapping[str, object]) -> None:
        issue = StoredIssue.from_payload(payload)
        self._issues[issue.id] = issue
        self._order.append(issue.id)
        match = _NUMERIC_ID_PATTERN.match(issue.id)
        if match and match.group("prefix") == self._prefix:
            self._next_numeric_id = max(self._next_numeric_id, int(match.group("value")) + 1)
        self._event_counter += 1

    def _repair_parent_child_links(self) -> None:
        for issue in self._issues.values():
            if issue.parent_id and issue.parent_id in self._issues:
                self._append_child(issue.parent_id, issue.id)

    def _append_child(self, parent_id: str, child_id: str) -> None:
        parent = self._require_issue(parent_id)
        parent.child_ids = _dedupe_strings((*parent.child_ids, child_id))

    def _allocate_issue_id(self) -> str:
        issue_id = f"{self._prefix}-{self._next_numeric_id}"
        self._next_numeric_id += 1
        return issue_id

    def _next_timestamp(self) -> str:
        self._event_counter += 1
        return _timestamp_for_event(self._event_counter)

    def _require_issue(self, issue_id: str) -> StoredIssue:
        issue = self._issues.get(issue_id)
        if issue is None:
            raise KeyError(issue_id)
        return issue

    def _has_work_children(self, issue_id: str) -> bool:
        issue = self._issues[issue_id]
        for child_id in issue.child_ids:
            child = self._issues.get(child_id)
            if child is None:
                continue
            if lifecycle.is_work_issue(labels=set(child.labels), issue_type=child.issue_type):
                return True
        return False

    def _dependencies_satisfied(self, issue: StoredIssue) -> bool:
        for dependency_id in issue.dependency_ids:
            dependency = self._issues.get(dependency_id)
            if dependency is None:
                return False
            if not lifecycle.dependency_issue_satisfied(
                status=dependency.status,
                labels=set(dependency.labels),
                require_integrated=True,
                review_state=self._dependency_review_state(dependency.id),
                issue_type=dependency.issue_type,
                has_work_children=self._has_work_children(dependency.id),
            ):
                return False
        return True

    def _dependency_review_state(self, issue_id: str) -> str | None:
        return changeset_fields.review_state(self._export_issue(issue_id))

    def _export_issue(self, issue_id: str) -> dict[str, object]:
        issue = self._issues[issue_id]
        payload: dict[str, object] = dict(issue.extra_fields)
        payload.update(
            {
                "id": issue.id,
                "title": issue.title,
                "issue_type": issue.issue_type,
                "status": issue.status,
                "labels": list(issue.labels),
                "dependencies": [
                    _issue_ref_for(self._issues, dependency_id)
                    for dependency_id in issue.dependency_ids
                ],
                "children": [
                    _issue_ref_for(self._issues, child_id) for child_id in issue.child_ids
                ],
            }
        )
        if issue.parent_id is not None:
            parent = self._issues.get(issue.parent_id)
            payload["parent"] = _issue_ref(issue.parent_id, title=parent.title if parent else None)
        if issue.description is not None:
            payload["description"] = issue.description
        if issue.design is not None:
            payload["design"] = issue.design
        if issue.acceptance_criteria is not None:
            payload["acceptance_criteria"] = issue.acceptance_criteria
        if issue.assignee is not None:
            payload["assignee"] = issue.assignee
        if issue.owner is not None:
            payload["owner"] = issue.owner
        if issue.priority is not None:
            payload["priority"] = issue.priority
        if issue.estimate is not None:
            payload["estimate"] = issue.estimate
        return payload


def _clean_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _append_issue_notes(
    description: str | None,
    append_notes: tuple[str, ...],
) -> str:
    base = description.rstrip("\n") if description else ""
    joined = "\n".join(note for note in append_notes if note)
    if not joined:
        return description or ""
    if not base:
        return f"{joined}\n"
    return f"{base}\n{joined}\n"


def _clean_slot_map(slot_map: Mapping[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for name, value in slot_map.items():
        normalized_name = name.strip()
        normalized_value = value.strip()
        if not normalized_name or not normalized_value:
            continue
        cleaned[normalized_name] = normalized_value
    return cleaned


__all__ = ["InMemoryIssueStore", "StoredIssue", "UNSET_UPDATE_FIELD"]
