"""Typed request/response models for the Beads client contract."""

from __future__ import annotations

from enum import Enum
from functools import total_ordering
from pathlib import Path
from re import Pattern, compile

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

_SEMVER_PATTERN: Pattern[str] = compile(r"^\s*v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\s*$")


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name=field_name)


def _normalize_string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _require_text(item, field_name=field_name)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return tuple(normalized)


class BeadsBoundaryModel(BaseModel):
    """Base model for Beads boundary contracts.

    Known fields validate strictly via explicit validators while unknown fields
    are preserved for forward compatibility with upstream ``bd`` payloads.
    """

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    @property
    def extra_fields(self) -> dict[str, object]:
        """Return unknown fields preserved during validation."""

        return dict(self.model_extra or {})


@total_ordering
class SemanticVersion(BeadsBoundaryModel):
    """Semantic version value object used by compatibility checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    major: int
    minor: int
    patch: int

    @model_validator(mode="before")
    @classmethod
    def _coerce_version(cls, value: object) -> object:
        if isinstance(value, cls):
            return value.model_dump()
        if isinstance(value, str):
            match = _SEMVER_PATTERN.match(value)
            if match is None:
                raise ValueError("semantic version must look like X.Y.Z")
            return {
                "major": int(match.group("major")),
                "minor": int(match.group("minor")),
                "patch": int(match.group("patch")),
            }
        if (
            isinstance(value, tuple)
            and len(value) == 3
            and all(isinstance(part, int) for part in value)
        ):
            return {"major": value[0], "minor": value[1], "patch": value[2]}
        return value

    @field_validator("major", "minor", "patch", mode="before")
    @classmethod
    def _validate_part(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("version parts must be integers")
        if value < 0:
            raise ValueError("version parts must be non-negative")
        return value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self.as_tuple() < other.as_tuple()

    def as_tuple(self) -> tuple[int, int, int]:
        """Return the version as a sortable tuple."""

        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class BeadsCapability(str, Enum):
    """Compatibility-gated Beads CLI capabilities."""

    VERSION_REPORTING = "version-reporting"
    ISSUE_JSON = "issue-json"
    ISSUE_MUTATION = "issue-mutation"
    DEPENDENCY_MUTATION = "dependency-mutation"
    READY_DISCOVERY = "ready-discovery"


class SupportedOperation(str, Enum):
    """Supported Beads operations in the public client contract."""

    CREATE = "create"
    UPDATE = "update"
    SHOW = "show"
    LIST = "list"
    CLOSE = "close"
    READY = "ready"
    DEPENDENCY_ADD = "dep-add"
    DEPENDENCY_REMOVE = "dep-remove"


class OperationOutputMode(str, Enum):
    """Expected output contract for an operation."""

    JSON_REQUIRED = "json-required"
    JSON_PREFERRED = "json-preferred"
    TEXT_NORMALIZED = "text-normalized"


class IssueReference(BeadsBoundaryModel):
    """Typed lightweight issue reference."""

    id: str
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_reference(cls, value: object) -> object:
        if isinstance(value, str):
            return {"id": value}
        return value

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> str:
        return _require_text(value, field_name="id")

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: object) -> str | None:
        return _optional_text(value, field_name="title")


class IssueRecord(BeadsBoundaryModel):
    """Typed issue payload returned by Beads read/write operations."""

    id: str
    title: str | None = None
    description: str | None = None
    design: str | None = None
    acceptance_criteria: str | None = None
    status: str | None = None
    type: str | None = None
    assignee: str | None = None
    owner: str | None = None
    priority: int | None = None
    estimate: int | None = None
    labels: tuple[str, ...] = ()
    parent: IssueReference | None = Field(
        default=None,
        validation_alias=AliasChoices("parent", "parent_id", "parentId"),
    )
    dependencies: tuple[IssueReference, ...] = Field(
        default=(),
        validation_alias=AliasChoices("dependencies", "dependency_ids", "dependencyIds"),
    )
    children: tuple[IssueReference, ...] = Field(
        default=(),
        validation_alias=AliasChoices("children", "child_ids", "childIds"),
    )

    @field_validator(
        "id",
        "title",
        "description",
        "design",
        "acceptance_criteria",
        "status",
        "type",
        "assignee",
        "owner",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: object, info: object) -> str | None:
        field_name = getattr(info, "field_name", "field")
        if field_name == "id":
            return _require_text(value, field_name=field_name)
        return _optional_text(value, field_name=field_name)

    @field_validator("priority", "estimate", mode="before")
    @classmethod
    def _normalize_int_fields(cls, value: object, info: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            field_name = getattr(info, "field_name", "field")
            raise ValueError(f"{field_name} must be an integer")
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, value: object) -> tuple[str, ...]:
        return _normalize_string_tuple(value, field_name="labels")

    @field_validator("dependencies", "children", mode="before")
    @classmethod
    def _normalize_references(cls, value: object, info: object) -> tuple[IssueReference, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            field_name = getattr(info, "field_name", "field")
            raise ValueError(f"{field_name} must be a list or tuple of issue references")
        refs: list[IssueReference] = []
        for item in value:
            refs.append(IssueReference.model_validate(item))
        return tuple(refs)


class ShowIssueRequest(BeadsBoundaryModel):
    """Request model for ``bd show``."""

    issue_id: str

    @field_validator("issue_id", mode="before")
    @classmethod
    def _normalize_issue_id(cls, value: object) -> str:
        return _require_text(value, field_name="issue_id")


class ListIssuesRequest(BeadsBoundaryModel):
    """Request model for ``bd list``."""

    parent_id: str | None = None
    status: str | None = None
    assignee: str | None = None
    title_query: str | None = None
    labels: tuple[str, ...] = ()
    include_closed: bool = False
    limit: int | None = None

    @field_validator("parent_id", "status", "assignee", "title_query", mode="before")
    @classmethod
    def _normalize_optional_text_fields(cls, value: object, info: object) -> str | None:
        field_name = getattr(info, "field_name", "field")
        return _optional_text(value, field_name=field_name)

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, value: object) -> tuple[str, ...]:
        return _normalize_string_tuple(value, field_name="labels")

    @field_validator("limit", mode="before")
    @classmethod
    def _normalize_limit(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("limit must be an integer")
        if value <= 0:
            raise ValueError("limit must be positive")
        return value


class ReadyIssuesRequest(BeadsBoundaryModel):
    """Request model for readiness and discovery flows."""

    parent_id: str | None = None

    @field_validator("parent_id", mode="before")
    @classmethod
    def _normalize_parent_id(cls, value: object) -> str | None:
        return _optional_text(value, field_name="parent_id")


class CreateIssueRequest(BeadsBoundaryModel):
    """Request model for ``bd create``."""

    title: str
    issue_type: str = Field(alias="type")
    description: str | None = None
    design: str | None = None
    acceptance_criteria: str | None = None
    status: str | None = None
    assignee: str | None = None
    parent_id: str | None = None
    priority: int | None = None
    estimate: int | None = None
    labels: tuple[str, ...] = ()

    @field_validator(
        "title",
        "issue_type",
        "description",
        "design",
        "acceptance_criteria",
        "status",
        "assignee",
        "parent_id",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: object, info: object) -> str | None:
        field_name = getattr(info, "field_name", "field")
        required_fields = {"title", "issue_type"}
        if field_name in required_fields:
            return _require_text(value, field_name=field_name)
        return _optional_text(value, field_name=field_name)

    @field_validator("priority", "estimate", mode="before")
    @classmethod
    def _normalize_numeric_fields(cls, value: object, info: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            field_name = getattr(info, "field_name", "field")
            raise ValueError(f"{field_name} must be an integer")
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, value: object) -> tuple[str, ...]:
        return _normalize_string_tuple(value, field_name="labels")


class UpdateIssueRequest(BeadsBoundaryModel):
    """Request model for ``bd update``."""

    issue_id: str
    title: str | None = None
    description: str | None = None
    design: str | None = None
    acceptance_criteria: str | None = None
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None
    estimate: int | None = None
    labels: tuple[str, ...] | None = None

    @field_validator(
        "issue_id",
        "title",
        "description",
        "design",
        "acceptance_criteria",
        "status",
        "assignee",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: object, info: object) -> str | None:
        field_name = getattr(info, "field_name", "field")
        if field_name == "issue_id":
            return _require_text(value, field_name=field_name)
        return _optional_text(value, field_name=field_name)

    @field_validator("priority", "estimate", mode="before")
    @classmethod
    def _normalize_numeric_fields(cls, value: object, info: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            field_name = getattr(info, "field_name", "field")
            raise ValueError(f"{field_name} must be an integer")
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        return _normalize_string_tuple(value, field_name="labels")

    @model_validator(mode="after")
    def _require_mutation(self) -> "UpdateIssueRequest":
        changes = (
            self.title,
            self.description,
            self.design,
            self.acceptance_criteria,
            self.status,
            self.assignee,
            self.priority,
            self.estimate,
            self.labels,
        )
        if all(value is None for value in changes):
            raise ValueError("update request must include at least one field change")
        return self


class CloseIssueRequest(BeadsBoundaryModel):
    """Request model for ``bd close``."""

    issue_id: str
    reason: str | None = None

    @field_validator("issue_id", "reason", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: object, info: object) -> str | None:
        field_name = getattr(info, "field_name", "field")
        if field_name == "issue_id":
            return _require_text(value, field_name=field_name)
        return _optional_text(value, field_name=field_name)


class DependencyMutationRequest(BeadsBoundaryModel):
    """Request model for dependency add/remove operations."""

    issue_id: str
    dependency_id: str

    @field_validator("issue_id", "dependency_id", mode="before")
    @classmethod
    def _normalize_ids(cls, value: object, info: object) -> str:
        field_name = getattr(info, "field_name", "field")
        return _require_text(value, field_name=field_name)


class BeadsCommandRequest(BeadsBoundaryModel):
    """Low-level transport request."""

    operation: SupportedOperation
    argv: tuple[str, ...]
    expects_json: bool = True
    cwd: Path | None = None
    env: dict[str, str] | None = None
    timeout_seconds: float | None = None

    @field_validator("argv", mode="before")
    @classmethod
    def _normalize_argv(cls, value: object) -> tuple[str, ...]:
        return _normalize_string_tuple(value, field_name="argv")

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _normalize_timeout(cls, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("timeout_seconds must be numeric")
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return float(value)


class BeadsCommandResult(BeadsBoundaryModel):
    """Low-level transport result."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @field_validator("argv", mode="before")
    @classmethod
    def _normalize_argv(cls, value: object) -> tuple[str, ...]:
        return _normalize_string_tuple(value, field_name="argv")

    @field_validator("returncode", mode="before")
    @classmethod
    def _normalize_returncode(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("returncode must be an integer")
        return value

    @field_validator("stdout", "stderr", mode="before")
    @classmethod
    def _normalize_streams(cls, value: object, info: object) -> str:
        field_name = getattr(info, "field_name", "field")
        if value is None:
            return ""
        return _require_text(value, field_name=field_name) if value != "" else ""


class BeadsEnvironment(BeadsBoundaryModel):
    """Installed ``bd`` environment snapshot used by compatibility checks."""

    version: SemanticVersion
    capabilities: tuple[BeadsCapability, ...] = ()

    @field_validator("capabilities", mode="before")
    @classmethod
    def _normalize_capabilities(cls, value: object) -> tuple[BeadsCapability, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("capabilities must be a list or tuple")
        normalized: list[BeadsCapability] = []
        seen: set[BeadsCapability] = set()
        for item in value:
            capability = BeadsCapability(item)
            if capability in seen:
                continue
            seen.add(capability)
            normalized.append(capability)
        return tuple(normalized)


def validate_issue_record(payload: object) -> IssueRecord:
    """Validate a Beads issue payload and return a typed record.

    Args:
        payload: Raw payload decoded from ``bd``.

    Returns:
        A validated issue record.

    Raises:
        ValidationError: If the payload does not match the issue schema.
    """

    try:
        return IssueRecord.model_validate(payload)
    except ValidationError:
        raise
