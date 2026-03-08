"""Typed request and response models for the Beads client contract."""

from __future__ import annotations

from enum import Enum
from functools import total_ordering
from pathlib import Path
from re import Pattern, compile
from typing import Annotated

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]
StrictStr = Annotated[str, StringConstraints(strict=True)]
StrictInt = Annotated[int, Field(strict=True)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
_SEMVER_PATTERN: Pattern[str] = compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)\s*$")


def _dedupe_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    return tuple(value for value in values if not (value in seen or seen.add(value)))


class BeadsModel(BaseModel):
    """Base model with strict known fields and passthrough extras."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    @property
    def extra_fields(self) -> dict[str, object]:
        """Return unknown fields preserved during validation."""

        return dict(self.model_extra or {})


@total_ordering
class SemanticVersion(BeadsModel):
    """Semantic version used by compatibility checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    major: Annotated[int, Field(strict=True, ge=0)]
    minor: Annotated[int, Field(strict=True, ge=0)]
    patch: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: object) -> object:
        if isinstance(value, cls):
            return value.model_dump()
        if isinstance(value, str):
            match = _SEMVER_PATTERN.match(value)
            if match is None:
                raise ValueError("semantic version must look like X.Y.Z")
            return {
                "major": int(match.group(1)),
                "minor": int(match.group(2)),
                "patch": int(match.group(3)),
            }
        if (
            isinstance(value, tuple)
            and len(value) == 3
            and all(isinstance(part, int) for part in value)
        ):
            return {"major": value[0], "minor": value[1], "patch": value[2]}
        return value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self.as_tuple() < other.as_tuple()

    def as_tuple(self) -> tuple[int, int, int]:
        """Return a sortable tuple form."""

        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class BeadsCapability(str, Enum):
    """Compatibility-gated CLI capabilities."""

    VERSION_REPORTING = "version-reporting"
    ISSUE_JSON = "issue-json"
    ISSUE_MUTATION = "issue-mutation"
    DEPENDENCY_MUTATION = "dependency-mutation"
    READY_DISCOVERY = "ready-discovery"


class SupportedOperation(str, Enum):
    """Supported Beads operations."""

    INSPECT_ENVIRONMENT = "inspect-environment"
    CREATE = "create"
    UPDATE = "update"
    SHOW = "show"
    LIST = "list"
    CLOSE = "close"
    READY = "ready"
    DEPENDENCY_ADD = "dep-add"
    DEPENDENCY_REMOVE = "dep-remove"


class OperationOutputMode(str, Enum):
    """Expected output contract per operation."""

    JSON_REQUIRED = "json-required"
    TEXT_NORMALIZED = "text-normalized"


class IssueReference(BeadsModel):
    """Typed issue reference."""

    id: NonBlankStr
    title: NonBlankStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value: object) -> object:
        return {"id": value} if isinstance(value, str) else value


class IssueRecord(BeadsModel):
    """Typed issue payload returned by Beads operations."""

    id: NonBlankStr
    title: NonBlankStr | None = None
    description: NonBlankStr | None = None
    design: NonBlankStr | None = None
    acceptance_criteria: NonBlankStr | None = None
    status: NonBlankStr | None = None
    type: NonBlankStr | None = Field(
        default=None,
        validation_alias=AliasChoices("type", "issue_type", "issueType"),
    )
    assignee: NonBlankStr | None = None
    owner: NonBlankStr | None = None
    priority: StrictInt | None = None
    estimate: StrictInt | None = None
    labels: tuple[NonBlankStr, ...] = ()
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

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_strings(value)

    @field_validator("dependencies", "children", mode="before")
    @classmethod
    def _coerce_refs(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("references must be a list or tuple")
        return tuple(IssueReference.model_validate(item) for item in value)


class ShowIssueRequest(BeadsModel):
    """Request model for show operations."""

    issue_id: NonBlankStr


class ListIssuesRequest(BeadsModel):
    """Request model for list operations."""

    parent_id: NonBlankStr | None = None
    status: NonBlankStr | None = None
    assignee: NonBlankStr | None = None
    title_query: NonBlankStr | None = None
    labels: tuple[NonBlankStr, ...] = ()
    include_closed: bool = False
    limit: PositiveInt | None = None

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_strings(value)


class ReadyIssuesRequest(BeadsModel):
    """Request model for readiness queries."""

    parent_id: NonBlankStr | None = None


class CreateIssueRequest(BeadsModel):
    """Request model for create operations."""

    title: NonBlankStr
    issue_type: NonBlankStr = Field(alias="type")
    description: NonBlankStr | None = None
    design: NonBlankStr | None = None
    acceptance_criteria: NonBlankStr | None = None
    status: NonBlankStr | None = None
    assignee: NonBlankStr | None = None
    parent_id: NonBlankStr | None = None
    priority: StrictInt | None = None
    estimate: StrictInt | None = None
    labels: tuple[NonBlankStr, ...] = ()

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_strings(value)


class UpdateIssueRequest(BeadsModel):
    """Request model for update operations."""

    issue_id: NonBlankStr
    title: NonBlankStr | None = None
    description: NonBlankStr | None = None
    design: NonBlankStr | None = None
    acceptance_criteria: NonBlankStr | None = None
    status: NonBlankStr | None = None
    assignee: NonBlankStr | None = None
    priority: StrictInt | None = None
    estimate: StrictInt | None = None
    labels: tuple[NonBlankStr, ...] | None = None

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else _dedupe_strings(value)

    @model_validator(mode="after")
    def _require_change(self) -> "UpdateIssueRequest":
        fields = (
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
        if all(value is None for value in fields):
            raise ValueError("update request must include at least one field change")
        return self


class CloseIssueRequest(BeadsModel):
    """Request model for close operations."""

    issue_id: NonBlankStr
    reason: NonBlankStr | None = None


class DependencyMutationRequest(BeadsModel):
    """Request model for dependency mutations."""

    issue_id: NonBlankStr
    dependency_id: NonBlankStr


class BeadsCommandRequest(BeadsModel):
    """Low-level transport request."""

    operation: SupportedOperation
    argv: tuple[NonBlankStr, ...]
    expects_json: bool = True
    cwd: Path | None = None
    env: dict[NonBlankStr, StrictStr] | None = None
    timeout_seconds: PositiveFloat | None = None


class BeadsCommandResult(BeadsModel):
    """Low-level transport result."""

    argv: tuple[NonBlankStr, ...]
    returncode: StrictInt
    stdout: StrictStr = ""
    stderr: StrictStr = ""
    timed_out: bool = False


class BeadsEnvironment(BeadsModel):
    """Installed ``bd`` version and capabilities."""

    version: SemanticVersion
    capabilities: tuple[BeadsCapability, ...] = ()

    @field_validator("capabilities")
    @classmethod
    def _dedupe_capabilities(
        cls,
        value: tuple[BeadsCapability, ...],
    ) -> tuple[BeadsCapability, ...]:
        seen: set[BeadsCapability] = set()
        return tuple(item for item in value if not (item in seen or seen.add(item)))
