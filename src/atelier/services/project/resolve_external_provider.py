"""Resolve init-time external provider choices with typed service contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from ... import external_registry
from ...io import confirm, select
from ...models import ProjectConfig
from ..result import ServiceResult, service_failure, service_success


class ProviderChooser(Protocol):
    """Typed selection dependency for provider prompts."""

    def __call__(
        self,
        text: str,
        choices: Sequence[str],
        default: str | None = None,
    ) -> str:
        """Return a selected provider option."""
        ...


class ConfirmChoice(Protocol):
    """Typed confirmation dependency for yes/no prompts."""

    def __call__(self, prompt: str, default: bool = False) -> bool:
        """Return confirmation response."""
        ...


class ResolvePlannerProvider(Protocol):
    """Typed dependency for provider candidate resolution."""

    def __call__(
        self,
        project_config: ProjectConfig,
        repo_root: Path,
        *,
        agent_name: str,
        project_data_dir: Path | None = None,
        agent_home: Path | None = None,
        interactive: bool = True,
        chooser: ProviderChooser | None = None,
    ) -> external_registry.PlannerProviderResolution:
        """Return provider resolution metadata."""
        ...


class ResolveExternalProviderRequest(BaseModel):
    """Input contract for provider-resolution behavior.

    Attributes:
        payload: Current project config payload.
        repo_root: Repository root path.
        agent_name: Active default agent for skill discovery.
        project_data_dir: Project data root used by skill lookup.
        stdin_isatty: Whether stdin is an interactive terminal.
        stdout_isatty: Whether stdout is an interactive terminal.
        yes: Whether init is running in non-interactive yes mode.
    """

    payload: ProjectConfig
    repo_root: Path
    agent_name: str
    project_data_dir: Path
    stdin_isatty: bool
    stdout_isatty: bool
    yes: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)


@dataclass(frozen=True)
class ResolveExternalProviderOutcome:
    """Outcome payload for provider-resolution service.

    Args:
        payload: Updated project config payload.
        selected_provider: Selected provider slug, or ``None``.
        messages: User-facing render lines in output order.
    """

    payload: ProjectConfig
    selected_provider: str | None
    messages: tuple[str, ...]


class ResolveExternalProviderService:
    """Resolve provider candidates and interactive selection for init."""

    def __init__(
        self,
        *,
        resolve_provider: ResolvePlannerProvider = external_registry.resolve_planner_provider,
        choose_provider: ProviderChooser = select,
        confirm_choice: ConfirmChoice = confirm,
    ) -> None:
        """Create the service with explicit resolver and prompt dependencies.

        Args:
            resolve_provider: Provider candidate resolver.
            choose_provider: Interactive selection callback.
            confirm_choice: Yes/no confirmation callback.
        """

        self._resolve_provider = resolve_provider
        self._choose_provider = choose_provider
        self._confirm_choice = confirm_choice

    def run(
        self, request: ResolveExternalProviderRequest
    ) -> ServiceResult[ResolveExternalProviderOutcome]:
        """Resolve provider selection and auto-export defaults.

        Args:
            request: Typed provider-resolution request.

        Returns:
            ``ServiceSuccess`` with updated config payload and output messages,
            or ``ServiceFailure`` with deterministic failure code.
        """

        if not request.agent_name.strip():
            return service_failure(
                code="validation_failed",
                message="agent_name must not be empty",
                recovery_hint="Configure a default agent before running init.",
            )

        try:
            provider_resolution = self._resolve_provider(
                request.payload,
                request.repo_root,
                agent_name=request.agent_name,
                project_data_dir=request.project_data_dir,
                # Keep prompting centralized in init so "none" stays available.
                interactive=False,
            )
        except SystemExit as exc:
            message = str(exc).strip() or "provider resolution failed"
            return service_failure(
                code="validation_failed",
                message=message,
                recovery_hint="Validate provider config and available skills.",
            )

        payload = request.payload
        selected_provider = provider_resolution.selected_provider
        current_provider = (payload.project.provider or "").strip().lower() or None
        current_auto_export = bool(payload.project.auto_export_new)
        interactive = request.stdin_isatty and request.stdout_isatty and not request.yes

        if interactive:
            available = list(provider_resolution.available_providers)
            if current_provider and current_provider not in available:
                available.append(current_provider)
            available = sorted(set(available))
            if available or current_provider:
                choices = ["none", *available]
                default_choice = selected_provider or current_provider or "none"
                if default_choice not in choices:
                    default_choice = "none"
                choice = self._choose_provider(
                    "External ticket provider",
                    choices,
                    default_choice,
                )
                selected_provider = None if choice == "none" else choice

        if selected_provider and selected_provider != current_provider:
            payload = payload.model_copy(deep=True)
            payload.project.provider = selected_provider
        if selected_provider is None and current_provider is not None:
            payload = payload.model_copy(deep=True)
            payload.project.provider = None

        messages = [
            (
                f"Selected external provider: {selected_provider}"
                if selected_provider
                else "Selected external provider: none"
            )
        ]

        next_auto_export = current_auto_export
        if selected_provider:
            if interactive:
                next_auto_export = self._confirm_choice(
                    f"Export all new epics/changesets to {selected_provider} by default?",
                    default=current_auto_export,
                )
        else:
            next_auto_export = False

        if next_auto_export != current_auto_export:
            payload = payload.model_copy(deep=True)
            payload.project.auto_export_new = next_auto_export

        messages.append(
            "Default auto-export for new epics/changesets: "
            + ("enabled" if bool(payload.project.auto_export_new) else "disabled")
        )

        return service_success(
            ResolveExternalProviderOutcome(
                payload=payload,
                selected_provider=selected_provider,
                messages=tuple(messages),
            )
        )
