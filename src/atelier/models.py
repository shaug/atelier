"""Pydantic models for Atelier configuration data."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import agents

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")
BranchHistory = Literal["manual", "squash", "merge", "rebase"]

UPGRADE_POLICY_VALUES = ("always", "ask", "manual")
UpgradePolicy = Literal["always", "ask", "manual"]

TICKET_PROVIDER_VALUES = ("none", "github", "linear")
TicketProvider = Literal["none", "github", "linear"]


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


class GitSection(BaseModel):
    """Git configuration for a project.

    Attributes:
        path: Git executable path (default ``git``).

    Example:
        >>> GitSection(path="/usr/bin/git")
        GitSection(...)
    """

    model_config = ConfigDict(extra="allow")

    path: str = "git"

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: object) -> object:
        if value is None:
            return "git"
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or "git"
        return value


class ProjectSection(BaseModel):
    """Project identification metadata.

    Attributes:
        enlistment: Absolute path to the local enlistment.
        origin: Normalized origin string.
        repo_url: Raw origin URL.
        allow_mainline_workspace: Allow a workspace on the default branch.
        provider: Provider slug (e.g. ``github``) when set.
        provider_url: Provider base URL (self-hosted).
        owner: Provider owner/org when set.

    Example:
        >>> ProjectSection(enlistment="/repo", origin="github.com/org/repo")
        ProjectSection(...)
    """

    model_config = ConfigDict(extra="allow")

    enlistment: str | None = None
    origin: str | None = None
    repo_url: str | None = None
    allow_mainline_workspace: bool = False
    provider: str | None = None
    provider_url: str | None = None
    owner: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("provider_url", "owner", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class ProjectProviderSection(BaseModel):
    """User-managed provider metadata for a project."""

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    provider_url: str | None = None
    owner: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("provider_url", "owner", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


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

    @field_validator("default", mode="before")
    @classmethod
    def normalize_default(cls, value: object) -> object:
        if value is None:
            return "codex"
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("default", mode="after")
    @classmethod
    def validate_default(cls, value: str) -> str:
        if not agents.is_supported_agent(value):
            raise ValueError(f"unsupported agent {value!r}")
        return value

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, list[str]] = {}
        for key, options in value.items():
            if not isinstance(options, list):
                continue
            normalized[str(key).strip().lower()] = [str(item) for item in options]
        return normalized

    @field_validator("options", mode="after")
    @classmethod
    def validate_options(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        unsupported = [key for key in value if not agents.is_supported_agent(key)]
        if unsupported:
            unsupported_str = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported agent options: {unsupported_str}")
        return value


class EditorConfig(BaseModel):
    """Editor configuration for the project.

    Attributes:
        edit: Blocking editor command for lightweight edits.
        work: Non-blocking editor command for opening the workspace repo.

    Example:
        >>> EditorConfig(edit=["subl", "-w"], work=["code"])
        EditorConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    edit: list[str] | None = None
    work: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_editor_config(cls, value: object) -> object:
        if isinstance(value, dict) and {"default", "options"} & set(value.keys()):
            raise ValueError(
                "legacy editor config detected; use editor.edit/editor.work instead"
            )
        return value

    @field_validator("edit", "work", mode="before")
    @classmethod
    def normalize_command(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        from . import command as command_util

        normalized = command_util.normalize_command(value)
        if normalized is None:
            raise ValueError(
                "editor commands must be lists of arguments or command strings"
            )
        return normalized


class TicketProviderConfig(BaseModel):
    """Ticket provider configuration for the project.

    Attributes:
        provider: Ticket provider name (none|github|linear).
        default_project: Optional default project identifier.
        default_namespace: Optional default namespace (org/team/etc).

    Example:
        >>> TicketProviderConfig(provider="github", default_project="org/repo")
        TicketProviderConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    provider: TicketProvider = "none"
    default_project: str | None = None
    default_namespace: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if value is None:
            return "none"
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("default_project", "default_namespace", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class TicketRefs(BaseModel):
    """Ticket references stored in workspace config."""

    model_config = ConfigDict(extra="allow")

    refs: list[str] = Field(default_factory=list)

    @field_validator("refs", mode="before")
    @classmethod
    def normalize_refs(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]


class AtelierSection(BaseModel):
    """Metadata for Atelier itself stored in configs.

    Attributes:
        version: Atelier version string.
        created_at: ISO-8601 UTC timestamp.
        upgrade: Template upgrade policy (always|ask|manual).
        managed_files: Hashes for managed files.

    Example:
        >>> AtelierSection(version="0.4.0", created_at="2026-01-18T00:00:00Z")
        AtelierSection(...)
    """

    model_config = ConfigDict(extra="allow")

    version: str | None = None
    created_at: str | None = None
    upgrade: UpgradePolicy | None = None
    managed_files: dict[str, str] = Field(default_factory=dict)

    @field_validator("upgrade", mode="before")
    @classmethod
    def normalize_upgrade(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("managed_files", mode="before")
    @classmethod
    def normalize_managed_files(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if item is None:
                continue
            normalized[str(key)] = str(item)
        return normalized


class AtelierSystemSection(BaseModel):
    """System-managed Atelier metadata stored in configs."""

    model_config = ConfigDict(extra="allow")

    version: str | None = None
    created_at: str | None = None
    managed_files: dict[str, str] = Field(default_factory=dict)

    @field_validator("managed_files", mode="before")
    @classmethod
    def normalize_managed_files(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if item is None:
                continue
            normalized[str(key)] = str(item)
        return normalized


class AtelierUserSection(BaseModel):
    """User-managed Atelier metadata stored in configs."""

    model_config = ConfigDict(extra="allow")

    upgrade: UpgradePolicy | None = None

    @field_validator("upgrade", mode="before")
    @classmethod
    def normalize_upgrade(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ProjectConfig(BaseModel):
    """Top-level project configuration model.

    Attributes:
        project: Project metadata section.
        git: Git configuration section.
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
    git: GitSection = Field(default_factory=GitSection)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    tickets: TicketProviderConfig = Field(default_factory=TicketProviderConfig)
    atelier: AtelierSection = Field(default_factory=AtelierSection)


class ProjectSystemConfig(BaseModel):
    """System-managed project configuration."""

    model_config = ConfigDict(extra="allow")

    project: ProjectSection = Field(default_factory=ProjectSection)
    atelier: AtelierSystemSection = Field(default_factory=AtelierSystemSection)


class ProjectUserConfig(BaseModel):
    """User-managed project configuration."""

    model_config = ConfigDict(extra="allow")

    project: ProjectProviderSection = Field(default_factory=ProjectProviderSection)
    git: GitSection = Field(default_factory=GitSection)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    tickets: TicketProviderConfig = Field(default_factory=TicketProviderConfig)
    atelier: AtelierUserSection = Field(default_factory=AtelierUserSection)


class WorkspaceSession(BaseModel):
    """Agent session metadata stored for a workspace.

    Attributes:
        agent: Agent name (e.g. ``codex``).
        id: Captured session ID.
        resume_command: Resume command string.

    Example:
        >>> WorkspaceSession(agent="codex", id="sess-1")
        WorkspaceSession(...)
    """

    model_config = ConfigDict(extra="allow")

    agent: str | None = None
    id: str | None = None
    resume_command: str | None = None


class WorkspaceBase(BaseModel):
    """Workspace base marker captured at creation time.

    Attributes:
        default_branch: Default branch name at capture time.
        sha: Commit SHA captured from the default branch head.
        captured_at: ISO-8601 UTC timestamp for when the base was recorded.

    Example:
        >>> WorkspaceBase(default_branch="main", sha="abc123")
        WorkspaceBase(...)
    """

    model_config = ConfigDict(extra="allow")

    default_branch: str | None = None
    sha: str | None = None
    captured_at: str | None = None

    @field_validator("default_branch", "sha", "captured_at", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class WorkspaceSection(BaseModel):
    """Workspace-specific configuration.

    Attributes:
        branch: Workspace branch name.
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).
        id: Workspace identifier string.
        uid: Unique workspace instance identifier.
        base: Captured base branch metadata.
        session: Agent session metadata.

    Example:
        >>> WorkspaceSection(branch="feat/demo", branch_pr=True, branch_history="manual")
        WorkspaceSection(...)
    """

    model_config = ConfigDict(extra="allow")

    branch: str
    branch_pr: bool = True
    branch_history: BranchHistory = "manual"
    id: str | None = None
    uid: str | None = None
    base: WorkspaceBase | None = None
    session: WorkspaceSession | None = None

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
    tickets: TicketRefs = Field(default_factory=TicketRefs)
    atelier: AtelierSection = Field(default_factory=AtelierSection)


class WorkspaceSystemConfig(BaseModel):
    """System-managed workspace configuration."""

    model_config = ConfigDict(extra="allow")

    workspace: WorkspaceSection
    atelier: AtelierSystemSection = Field(default_factory=AtelierSystemSection)


class WorkspaceUserConfig(BaseModel):
    """User-managed workspace configuration."""

    model_config = ConfigDict(extra="allow")

    tickets: TicketRefs = Field(default_factory=TicketRefs)
    atelier: AtelierUserSection = Field(default_factory=AtelierUserSection)
