"""Pydantic models for Atelier configuration data."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import agents

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")
BranchHistory = Literal["manual", "squash", "merge", "rebase"]
BRANCH_SQUASH_MESSAGE_VALUES = ("deterministic", "agent")
BranchSquashMessage = Literal["deterministic", "agent"]
BRANCH_PR_MODE_VALUES = ("none", "draft", "ready")
BranchPrMode = Literal["none", "draft", "ready"]
WORKER_SELECT_VALUES = ("first-eligible", "oldest-feedback")
WorkerSelectMode = Literal["first-eligible", "oldest-feedback"]

UPGRADE_POLICY_VALUES = ("always", "ask", "manual")
UpgradePolicy = Literal["always", "ask", "manual"]

BEADS_LOCATION_VALUES = ("repo", "project")
BeadsLocation = Literal["repo", "project"]
BEADS_RUNTIME_MODE_VALUES = ("dolt-server",)
BeadsRuntimeMode = Literal["dolt-server"]
BEADS_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,15}$")


class BranchConfig(BaseModel):
    """Branch policy configuration for a project.

    Attributes:
        prefix: Prefix applied to workspace branches.
        pr_mode: Pull request mode (none|draft|ready).
        history: History policy (manual|squash|merge|rebase).
        squash_message: Squash commit message policy (deterministic|agent).

    Example:
        >>> BranchConfig(prefix="scott/", pr_mode="none", history="rebase")
        BranchConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    prefix: str = ""
    pr_mode: BranchPrMode = "none"
    history: BranchHistory = "manual"
    squash_message: BranchSquashMessage = "deterministic"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_pr(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload.pop("pr_strategy", None)
        legacy_pr = payload.pop("pr", None)
        if "pr_mode" in payload and payload.get("pr_mode") is not None:
            return payload
        if legacy_pr is None:
            return payload
        if isinstance(legacy_pr, bool):
            payload["pr_mode"] = "draft" if legacy_pr else "none"
            return payload
        if isinstance(legacy_pr, str):
            normalized = legacy_pr.strip().lower()
            if normalized in {"true", "yes", "1"}:
                payload["pr_mode"] = "draft"
                return payload
            if normalized in {"false", "no", "0"}:
                payload["pr_mode"] = "none"
                return payload
        raise ValueError("pr must be a boolean when branch.pr_mode is unset")

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

    @field_validator("pr_mode", mode="before")
    @classmethod
    def normalize_pr_mode(cls, value: object) -> object:
        if value is None:
            return "none"
        if isinstance(value, str):
            normalized = value.strip().lower().replace("_", "-")
            if not normalized:
                return "none"
            if normalized in BRANCH_PR_MODE_VALUES:
                return normalized
        raise ValueError("pr_mode must be one of: " + ", ".join(BRANCH_PR_MODE_VALUES))

    @field_validator("squash_message", mode="before")
    @classmethod
    def normalize_squash_message(cls, value: object) -> object:
        if value is None:
            return "deterministic"
        if isinstance(value, str):
            normalized = value.strip().lower().replace("_", "-")
            if not normalized:
                return "deterministic"
            if normalized in BRANCH_SQUASH_MESSAGE_VALUES:
                return normalized
        raise ValueError(
            "squash_message must be one of: " + ", ".join(BRANCH_SQUASH_MESSAGE_VALUES)
        )

    @property
    def pr(self) -> bool:
        """Return whether pull requests are enabled for this branch policy."""
        return self.pr_mode != "none"

    @property
    def pr_strategy(self) -> Literal["sequential"]:
        """Return the only supported PR strategy for compatibility callers."""
        return "sequential"


class WorkerConfig(BaseModel):
    """Worker startup selection policy configuration.

    Attributes:
        select: Startup selector policy
            (first-eligible|oldest-feedback).

    Example:
        >>> WorkerConfig(select="first-eligible")
        WorkerConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    select: WorkerSelectMode = "oldest-feedback"

    @field_validator("select", mode="before")
    @classmethod
    def normalize_select(cls, value: object) -> object:
        if value is None:
            return "oldest-feedback"
        if not isinstance(value, str):
            raise ValueError("select must be one of: " + ", ".join(WORKER_SELECT_VALUES))
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            return "oldest-feedback"
        if normalized in WORKER_SELECT_VALUES:
            return normalized
        raise ValueError("select must be one of: " + ", ".join(WORKER_SELECT_VALUES))


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
        auto_export_new: Export newly created epics/changesets by default.
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
    auto_export_new: bool = False
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
        options: Legacy global mapping of agent names to argument lists.
        launch_options: Role-scoped options keyed by ``planner``/``worker``,
            then agent name.

    Example:
        >>> AgentConfig(
        ...     default="codex",
        ...     options={"codex": ["--profile", "fast"]},
        ... )
        AgentConfig(...)
    """

    model_config = ConfigDict(extra="allow")

    default: str = "codex"
    identity: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)
    launch_options: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

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

    @field_validator("identity", mode="before")
    @classmethod
    def normalize_identity(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
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

    @field_validator("launch_options", mode="before")
    @classmethod
    def normalize_launch_options(cls, value: object) -> dict[str, dict[str, list[str]]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, dict[str, list[str]]] = {}
        for role, role_options in value.items():
            normalized_role = agents.normalize_launch_role(str(role))
            if not normalized_role:
                supported = ", ".join(agents.LAUNCH_ROLE_VALUES)
                raise ValueError(f"unsupported launch option role {role!r}; supported: {supported}")
            if not isinstance(role_options, dict):
                continue
            normalized_agents: dict[str, list[str]] = {}
            for agent_name, options in role_options.items():
                if not isinstance(options, list):
                    continue
                normalized_agent = str(agent_name).strip().lower()
                if not normalized_agent:
                    continue
                normalized_agents[normalized_agent] = [str(item) for item in options]
            normalized[normalized_role] = normalized_agents
        return normalized

    @field_validator("launch_options", mode="after")
    @classmethod
    def validate_launch_options(
        cls, value: dict[str, dict[str, list[str]]]
    ) -> dict[str, dict[str, list[str]]]:
        unsupported_roles = [role for role in value if role not in agents.LAUNCH_ROLE_VALUES]
        if unsupported_roles:
            supported = ", ".join(agents.LAUNCH_ROLE_VALUES)
            unsupported = ", ".join(sorted(unsupported_roles))
            raise ValueError(
                f"unsupported launch option roles: {unsupported} (supported: {supported})"
            )
        unsupported_agents: set[str] = set()
        for role_options in value.values():
            unsupported_agents.update(
                name for name in role_options if not agents.is_supported_agent(name)
            )
        if unsupported_agents:
            unsupported_str = ", ".join(sorted(unsupported_agents))
            raise ValueError(f"unsupported launch option agents: {unsupported_str}")
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
            raise ValueError("legacy editor config detected; use editor.edit/editor.work instead")
        return value

    @field_validator("edit", "work", mode="before")
    @classmethod
    def normalize_command(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        from . import command as command_util

        normalized = command_util.normalize_command(value)
        if normalized is None:
            raise ValueError("editor commands must be lists of arguments or command strings")
        return normalized


class BeadsSection(BaseModel):
    """Beads configuration for a project."""

    model_config = ConfigDict(extra="allow")

    location: BeadsLocation | None = None
    runtime_mode: BeadsRuntimeMode | None = None
    prefix: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_runtime_mode(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if payload.get("runtime_mode") is not None:
            if payload.get("prefix") is None and payload.get("issue_prefix") is not None:
                payload["prefix"] = payload.get("issue_prefix")
            return payload
        legacy_runtime = payload.get("mode")
        if legacy_runtime is not None:
            payload["runtime_mode"] = legacy_runtime
        if payload.get("prefix") is None and payload.get("issue_prefix") is not None:
            payload["prefix"] = payload.get("issue_prefix")
        return payload

    @field_validator("location", mode="before")
    @classmethod
    def normalize_location(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("runtime_mode", mode="before")
    @classmethod
    def normalize_runtime_mode(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("runtime_mode must be one of: " + ", ".join(BEADS_RUNTIME_MODE_VALUES))
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            return None
        if normalized in {"server", "dolt", "doltserver"}:
            return "dolt-server"
        if normalized in BEADS_RUNTIME_MODE_VALUES:
            return normalized
        raise ValueError("runtime_mode must be one of: " + ", ".join(BEADS_RUNTIME_MODE_VALUES))

    @field_validator("prefix", mode="before")
    @classmethod
    def normalize_prefix(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("prefix must be a string like at or ts2")
        normalized = value.strip().lower()
        if not normalized:
            return None
        if not BEADS_PREFIX_PATTERN.match(normalized):
            raise ValueError("prefix must match ^[a-z][a-z0-9]{0,15}$ (for example: at, ts, ts2)")
        return normalized


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
    data_dir: str | None = None
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

    @field_validator("data_dir", mode="before")
    @classmethod
    def normalize_data_dir(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
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
    data_dir: str | None = None
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

    @field_validator("data_dir", mode="before")
    @classmethod
    def normalize_system_data_dir(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class SkillMetadata(BaseModel):
    """Metadata stored for an Atelier-managed skill."""

    model_config = ConfigDict(extra="allow")

    version: str | None = None
    hash: str | None = None

    @field_validator("version", "hash", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


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
        worker: Worker policy section.
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
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    beads: BeadsSection = Field(default_factory=BeadsSection)
    atelier: AtelierSection = Field(default_factory=AtelierSection)


class ProjectSystemConfig(BaseModel):
    """System-managed project configuration."""

    model_config = ConfigDict(extra="allow")

    project: ProjectSection = Field(default_factory=ProjectSection)
    beads: BeadsSection = Field(default_factory=BeadsSection)
    atelier: AtelierSystemSection = Field(default_factory=AtelierSystemSection)


class ProjectUserConfig(BaseModel):
    """User-managed project configuration."""

    model_config = ConfigDict(extra="allow")

    project: ProjectProviderSection = Field(default_factory=ProjectProviderSection)
    git: GitSection = Field(default_factory=GitSection)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    atelier: AtelierUserSection = Field(default_factory=AtelierUserSection)
