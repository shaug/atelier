from __future__ import annotations

from types import SimpleNamespace

from atelier.models import ProjectConfig
from atelier.services import ServiceFailure, ServiceSuccess
from atelier.services.project import (
    ComposeProjectConfigRequest,
    ComposeProjectConfigService,
)


def test_compose_project_config_service_success() -> None:
    captured: dict[str, object] = {}

    def fake_build(
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
        captured["existing"] = existing
        captured["enlistment_path"] = enlistment_path
        captured["origin"] = origin
        captured["origin_raw"] = origin_raw
        captured["args"] = args
        captured["prompt_missing_only"] = prompt_missing_only
        captured["raw_existing"] = raw_existing
        captured["allow_editor_empty"] = allow_editor_empty
        return ProjectConfig()

    request = ComposeProjectConfigRequest(
        existing={},
        enlistment_path="/repo",
        origin="github.com/acme/widgets",
        origin_raw="git@github.com:acme/widgets.git",
        args=SimpleNamespace(),
        prompt_missing_only=True,
        raw_existing={"branch": {"prefix": "scott/"}},
        allow_editor_empty=True,
    )
    result = ComposeProjectConfigService(build_config=fake_build).run(request)

    assert isinstance(result, ServiceSuccess)
    assert isinstance(result.outcome.payload, ProjectConfig)
    assert captured["enlistment_path"] == "/repo"
    assert captured["prompt_missing_only"] is True


def test_compose_project_config_service_validation_failure_for_empty_enlistment() -> None:
    request = ComposeProjectConfigRequest(
        existing={},
        enlistment_path=" ",
        origin=None,
        origin_raw=None,
        args=SimpleNamespace(),
    )
    result = ComposeProjectConfigService(build_config=lambda *args, **kwargs: ProjectConfig()).run(
        request
    )

    assert isinstance(result, ServiceFailure)
    assert result.code == "validation_failed"


def test_compose_project_config_service_maps_builder_system_exit() -> None:
    def failing_build(*args: object, **kwargs: object) -> ProjectConfig:
        raise SystemExit("branch history is invalid")

    request = ComposeProjectConfigRequest(
        existing={},
        enlistment_path="/repo",
        origin="github.com/acme/widgets",
        origin_raw="git@github.com:acme/widgets.git",
        args=SimpleNamespace(),
    )
    result = ComposeProjectConfigService(build_config=failing_build).run(request)

    assert isinstance(result, ServiceFailure)
    assert result.code == "validation_failed"
    assert "branch history is invalid" in result.message
