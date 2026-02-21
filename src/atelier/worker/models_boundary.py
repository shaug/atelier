"""Pydantic models for worker-facing external boundary payloads."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_DEPENDENCY_ID_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\b")


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_parent_child_relation(value: object) -> bool:
    if isinstance(value, dict):
        relation = value.get("relation")
        return isinstance(relation, str) and relation.strip().lower() == "parent-child"
    if isinstance(value, str):
        return "parent-child" in value.lower()
    return False


def _extract_dependency_id(value: object) -> str | None:
    if _is_parent_child_relation(value):
        return None
    if isinstance(value, dict):
        issue_id = _clean_str(value.get("id"))
        if issue_id:
            return issue_id
        nested_issue = value.get("issue")
        if isinstance(nested_issue, dict):
            nested_id = _clean_str(nested_issue.get("id"))
            if nested_id:
                return nested_id
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    match = _DEPENDENCY_ID_PATTERN.match(text)
    if not match:
        return None
    return match.group(1).strip() or None


class BeadsIssueBoundary(BaseModel):
    """Validated issue payload used by worker selection/finalization logic."""

    model_config = ConfigDict(extra="allow")

    id: str
    status: str | None = None
    labels: tuple[str, ...] = ()
    parent_id: str | None = None
    dependency_ids: tuple[str, ...] = ()

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> object:
        normalized = _clean_str(value)
        if normalized is None:
            raise ValueError("missing issue id")
        return normalized

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        return _clean_str(value)

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        normalized: list[str] = []
        seen: set[str] = set()
        for entry in value:
            label = _clean_str(entry)
            if not label or label in seen:
                continue
            seen.add(label)
            normalized.append(label)
        return tuple(normalized)

    @field_validator("parent_id", mode="before")
    @classmethod
    def _normalize_parent(cls, value: object) -> object:
        if isinstance(value, dict):
            return _clean_str(value.get("id"))
        return _clean_str(value)

    @field_validator("dependency_ids", mode="before")
    @classmethod
    def _normalize_dependencies(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        deps: list[str] = []
        seen: set[str] = set()
        for entry in value:
            dep_id = _extract_dependency_id(entry)
            if not dep_id or dep_id in seen:
                continue
            seen.add(dep_id)
            deps.append(dep_id)
        return tuple(deps)


class GithubAuthorBoundary(BaseModel):
    """Normalized GitHub user/author payload."""

    model_config = ConfigDict(extra="allow")

    login: str | None = None
    is_bot: bool | None = Field(default=None, alias="isBot")
    type: str | None = None

    @field_validator("login", "type", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        return _clean_str(value)


class GithubReviewRequestBoundary(BaseModel):
    """Review request entry payload."""

    model_config = ConfigDict(extra="allow")

    requested_reviewer: GithubAuthorBoundary | None = Field(
        default=None, alias="requestedReviewer"
    )


class GithubCommentBoundary(BaseModel):
    """PR comment payload (top-level comments)."""

    model_config = ConfigDict(extra="allow")

    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    author: GithubAuthorBoundary | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _normalize_timestamps(cls, value: object) -> object:
        return _clean_str(value)


class GithubReviewBoundary(BaseModel):
    """PR review event payload."""

    model_config = ConfigDict(extra="allow")

    state: str | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    submitted_at: str | None = Field(default=None, alias="submittedAt")
    author: GithubAuthorBoundary | None = None

    @field_validator("state", "created_at", "updated_at", "submitted_at", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        return _clean_str(value)


class GithubPullRequestBoundary(BaseModel):
    """Validated GitHub PR payload used for lifecycle/review decisions."""

    model_config = ConfigDict(extra="allow")

    number: int | None = None
    url: str | None = None
    state: str | None = None
    base_ref_name: str | None = Field(default=None, alias="baseRefName")
    head_ref_name: str | None = Field(default=None, alias="headRefName")
    is_draft: bool = Field(default=False, alias="isDraft")
    merged_at: str | None = Field(default=None, alias="mergedAt")
    closed_at: str | None = Field(default=None, alias="closedAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    review_decision: str | None = Field(default=None, alias="reviewDecision")
    review_requests: tuple[GithubReviewRequestBoundary, ...] = Field(
        default=(), alias="reviewRequests"
    )
    comments: tuple[GithubCommentBoundary, ...] = ()
    reviews: tuple[GithubReviewBoundary, ...] = ()

    @field_validator(
        "url",
        "state",
        "base_ref_name",
        "head_ref_name",
        "merged_at",
        "closed_at",
        "updated_at",
        "review_decision",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        return _clean_str(value)

    @field_validator("number", mode="before")
    @classmethod
    def _normalize_number(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        raise ValueError("number must be an integer")

    @property
    def payload(self) -> dict[str, Any]:
        """Return normalized payload mapping for compatibility call sites."""
        return self.model_dump(by_alias=True, exclude_none=True)


class ReviewFeedbackBoundary(BaseModel):
    """Validated review-feedback snapshot for worker state transitions."""

    model_config = ConfigDict(extra="ignore")

    feedback_at: str | None = None
    unresolved_threads: int | None = Field(default=None, ge=0)
    branch_head: str | None = None

    @field_validator("feedback_at", "branch_head", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        return _clean_str(value)


def parse_issue_boundary(
    raw_issue: dict[str, object], *, source: str
) -> BeadsIssueBoundary:
    """Validate a Beads issue payload for worker decision logic."""
    payload = dict(raw_issue)
    if "parent_id" not in payload:
        payload["parent_id"] = raw_issue.get("parent")
    if "dependency_ids" not in payload:
        payload["dependency_ids"] = raw_issue.get("dependencies")
    try:
        return BeadsIssueBoundary.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid beads issue payload ({source}): {exc}") from exc


def parse_pr_boundary(
    raw_payload: dict[str, object] | None, *, source: str
) -> GithubPullRequestBoundary | None:
    """Validate a GitHub PR payload and return normalized boundary model."""
    if raw_payload is None:
        return None
    try:
        return GithubPullRequestBoundary.model_validate(raw_payload)
    except ValidationError as exc:
        raise ValueError(f"invalid github PR payload ({source}): {exc}") from exc


def parse_review_feedback_boundary(
    *,
    feedback_at: str | None,
    unresolved_threads: int | None,
    branch_head: str | None,
    source: str,
) -> ReviewFeedbackBoundary:
    """Validate review-feedback snapshot fields from external boundaries."""
    try:
        return ReviewFeedbackBoundary.model_validate(
            {
                "feedback_at": feedback_at,
                "unresolved_threads": unresolved_threads,
                "branch_head": branch_head,
            }
        )
    except ValidationError as exc:
        raise ValueError(f"invalid review feedback payload ({source}): {exc}") from exc
