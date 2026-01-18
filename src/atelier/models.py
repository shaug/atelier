from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")
BranchHistory = Literal["manual", "squash", "merge", "rebase"]


class BranchConfig(BaseModel):
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
    model_config = ConfigDict(extra="allow")

    origin: str | None = None
    repo_url: str | None = None


class AgentConfig(BaseModel):
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
    model_config = ConfigDict(extra="allow")

    version: str | None = None
    created_at: str | None = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: ProjectSection = Field(default_factory=ProjectSection)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    atelier: AtelierSection = Field(default_factory=AtelierSection)


class WorkspaceSection(BaseModel):
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
    model_config = ConfigDict(extra="allow")

    workspace: WorkspaceSection
    atelier: AtelierSection = Field(default_factory=AtelierSection)
