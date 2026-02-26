from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from ... import external_registry
from ...io import confirm, select
from ...models import ProjectConfig
from ..errors import ValidationFailedError

ProviderChooser = Callable[[str, Sequence[str], str | None], str]
ConfirmChoice = Callable[[str, bool], bool]
ResolveProvider = Callable[..., external_registry.PlannerProviderResolution]


class ResolveExternalProviderRequest(BaseModel):
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
    payload: ProjectConfig
    selected_provider: str | None
    messages: tuple[str, ...]


class ResolveExternalProviderService:
    def __init__(
        self,
        *,
        resolve_provider: ResolveProvider = external_registry.resolve_planner_provider,
        choose_provider: ProviderChooser = select,
        confirm_choice: ConfirmChoice = confirm,
    ) -> None:
        self._resolve_provider = resolve_provider
        self._choose_provider = choose_provider
        self._confirm_choice = confirm_choice

    def run(self, request: ResolveExternalProviderRequest) -> ResolveExternalProviderOutcome:
        if not request.agent_name.strip():
            raise ValidationFailedError("agent_name must not be empty")

        try:
            resolution = self._resolve_provider(
                request.payload,
                request.repo_root,
                agent_name=request.agent_name,
                project_data_dir=request.project_data_dir,
                interactive=False,
            )
        except SystemExit as exc:
            raise ValidationFailedError(
                "provider resolution failed",
                recovery_hint=str(exc).strip() or None,
            ) from exc

        payload = request.payload
        selected = resolution.selected_provider
        current = (payload.project.provider or "").strip().lower() or None
        auto_export = bool(payload.project.auto_export_new)
        interactive = request.stdin_isatty and request.stdout_isatty and not request.yes

        if interactive:
            available = list(resolution.available_providers)
            if current and current not in available:
                available.append(current)
            available = sorted(set(available))
            if available or current:
                choices = ["none", *available]
                default = selected or current or "none"
                if default not in choices:
                    default = "none"
                choice = self._choose_provider("External ticket provider", choices, default)
                selected = None if choice == "none" else choice

        if selected != current:
            payload = payload.model_copy(deep=True)
            payload.project.provider = selected

        if selected and interactive:
            next_auto_export = self._confirm_choice(
                f"Export all new epics/changesets to {selected} by default?",
                auto_export,
            )
        else:
            next_auto_export = False if not selected else auto_export

        if next_auto_export != auto_export:
            payload = payload.model_copy(deep=True)
            payload.project.auto_export_new = next_auto_export

        messages = (
            f"Selected external provider: {selected}"
            if selected
            else "Selected external provider: none",
            "Default auto-export for new epics/changesets: "
            + ("enabled" if bool(payload.project.auto_export_new) else "disabled"),
        )
        return ResolveExternalProviderOutcome(payload, selected, messages)
