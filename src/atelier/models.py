"""Pydantic models for Atelier configuration data."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")
BranchHistory = Literal["manual", "squash", "merge", "rebase"]


class BranchConfig(BaseModel):
    """Branch policy configuration for a project.

    Attributes:
        prefix: Prefix applied to workspace branches.
        pr: Whether pull requests are expected.
        history: History policy (manual|squash|merge|rebase).

    Example:
        >>> BranchConfig(prefix="scott/", pr=False, history="rebase")
        BranchConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    prefix: str = ""
    pr: bool = True
    history: BranchHistory = "manual"

    @field_validator("prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: object) -> object:
        if value is None:
            return ""
        return value

    @field_validator("history", mode="before")
    @classmethod
    def normalize_history(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ProjectSection(BaseModel):
    """Project identification metadata.

    Attributes:
        enlistment: Absolute path to the local enlistment.
        origin: Normalized origin string.
        repo_url: Raw origin URL.

    Example:
        >>> ProjectSection(enlistment="/repo", origin="github.com/org/repo")
        ProjectSection(...)
    """

    model_config = ConfigDict(extra="allow")

    enlistment: str | None = None
    origin: str | None = None
    repo_url: str | None = None


class AgentConfig(BaseModel):
    """Agent configuration for the project.

    Attributes:
        default: Default agent name.
        options: Mapping of agent names to argument lists.

    Example:
        >>> AgentConfig(default="codex", options={"codex": ["--profile", "fast"]})
        AgentConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    default: str = "codex"
    options: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, list[str]] = {}
        for key, options in value.items():
            if not isinstance(options, list):
                continue
            normalized[str(key)] = [str(item) for item in options]
        return normalized


class EditorConfig(BaseModel):
    """Editor configuration for the project.

    Attributes:
        default: Default editor command.
        options: Mapping of editor names to argument lists.

    Example:
        >>> EditorConfig(default="cursor", options={"cursor": ["--reuse-window"]})
        EditorConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    default: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, list[str]] = {}
        for key, options in value.items():
            if not isinstance(options, list):
                continue
            normalized[str(key)] = [str(item) for item in options]
        return normalized


class AtelierSection(BaseModel):
    """Metadata for Atelier itself stored in configs.

    Attributes:
        version: Atelier version string.
        created_at: ISO-8601 UTC timestamp.

    Example:
        >>> AtelierSection(version="0.4.0", created_at="2026-01-18T00:00:00Z")
        AtelierSection(...)
    """

    model_config = ConfigDict(extra="allow")

    version: str | None = None
    created_at: str | None = None


class ProjectConfig(BaseModel):
    """Top-level project configuration model.

    Attributes:
        project: Project metadata section.
        branch: Branch policy section.
        agent: Agent configuration section.
        editor: Editor configuration section.
        atelier: Atelier metadata section.

    Example:
        >>> ProjectConfig(project=ProjectSection(origin="github.com/org/repo"))
        ProjectConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    project: ProjectSection = Field(default_factory=ProjectSection)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    atelier: AtelierSection = Field(default_factory=AtelierSection)


class WorkspaceSection(BaseModel):
    """Workspace-specific configuration.

    Attributes:
        branch: Workspace branch name.
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).
        id: Workspace identifier string.

    Example:
        >>> WorkspaceSection(branch="feat/demo", branch_pr=True, branch_history="manual")
        WorkspaceSection(...)
    """

    model_config = ConfigDict(extra="allow")

    branch: str
    branch_pr: bool = True
    branch_history: BranchHistory = "manual"
    id: str | None = None

    @field_validator("branch_history", mode="before")
    @classmethod
    def normalize_branch_history(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("branch")
    @classmethod
    def branch_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("branch must not be empty")
        return value


class WorkspaceConfig(BaseModel):
    """Top-level workspace configuration model.

    Attributes:
        workspace: Workspace section.
        atelier: Atelier metadata section.

    Example:
        >>> WorkspaceConfig(workspace=WorkspaceSection(branch="feat/demo"))
        WorkspaceConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    workspace: WorkspaceSection
    atelier: AtelierSection = Field(default_factory=AtelierSection)
