"""Compose project configuration behind a typed service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ... import config
from ...models import ProjectConfig
from ..result import ServiceResult, service_failure, service_success


class BuildProjectConfig(Protocol):
    """Typed callable for project config composition."""

    def __call__(
        self,
        existing: ProjectConfig | dict,
        enlistment_path: str,
        origin: str | None,
        origin_raw: str | None,
        args: object | None,
        *,
        prompt_missing_only: bool = False,
        raw_existing: dict | None = None,
        allow_editor_empty: bool = False,
    ) -> ProjectConfig:
        """Build a project configuration payload."""
        ...


class ComposeProjectConfigRequest(BaseModel):
    """Input contract for project config composition.

    Attributes:
        existing: Existing project configuration payload.
        enlistment_path: Resolved enlistment root path.
        origin: Normalized repository origin.
        origin_raw: Raw repository origin URL.
        args: Parsed CLI args used for overrides/prompts.
        prompt_missing_only: Prompt only for fields missing from config.
        raw_existing: Raw config payload used to detect missing fields.
        allow_editor_empty: Allow clearing editor command values.
    """

    existing: ProjectConfig | dict
    enlistment_path: str
    origin: str | None
    origin_raw: str | None
    args: object | None
    prompt_missing_only: bool = False
    raw_existing: dict | None = None
    allow_editor_empty: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)


@dataclass(frozen=True)
class ComposeProjectConfigOutcome:
    """Outcome payload for project config composition.

    Args:
        payload: Fully composed project config.
    """

    payload: ProjectConfig


class ComposeProjectConfigService:
    """Compose project config and map expected failures to stable codes."""

    def __init__(self, *, build_config: BuildProjectConfig = config.build_project_config) -> None:
        """Create the service with explicit config builder dependency.

        Args:
            build_config: Callable used to build project config payloads.
        """

        self._build_config = build_config

    def run(
        self, request: ComposeProjectConfigRequest
    ) -> ServiceResult[ComposeProjectConfigOutcome]:
        """Compose project config from a typed request.

        Args:
            request: Typed config-composition request.

        Returns:
            ``ServiceSuccess`` with composed payload or ``ServiceFailure`` with
            a deterministic failure code.
        """

        if not request.enlistment_path.strip():
            return service_failure(
                code="validation_failed",
                message="enlistment_path must not be empty",
                recovery_hint="Resolve the repository root before running init.",
            )
        try:
            payload = self._build_config(
                request.existing,
                request.enlistment_path,
                request.origin,
                request.origin_raw,
                request.args,
                prompt_missing_only=request.prompt_missing_only,
                raw_existing=request.raw_existing,
                allow_editor_empty=request.allow_editor_empty,
            )
        except SystemExit as exc:
            message = str(exc).strip() or "project config validation failed"
            return service_failure(
                code="validation_failed",
                message=message,
                recovery_hint="Review init options and existing config values.",
            )
        return service_success(ComposeProjectConfigOutcome(payload=payload))
