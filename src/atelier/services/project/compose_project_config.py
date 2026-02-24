from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict

from ... import config
from ...models import ProjectConfig
from ..result import ServiceFailure, ServiceResult, ServiceSuccess

BuildProjectConfig = Callable[..., ProjectConfig]


class ComposeProjectConfigRequest(BaseModel):
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
    payload: ProjectConfig


class ComposeProjectConfigService:
    def __init__(self, *, build_config: BuildProjectConfig = config.build_project_config) -> None:
        self._build_config = build_config

    def run(
        self, request: ComposeProjectConfigRequest
    ) -> ServiceResult[ComposeProjectConfigOutcome]:
        if not request.enlistment_path.strip():
            return ServiceFailure("validation_failed", "enlistment_path must not be empty")
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
            return ServiceFailure(
                "validation_failed",
                str(exc).strip() or "project config validation failed",
            )
        return ServiceSuccess(ComposeProjectConfigOutcome(payload=payload))
