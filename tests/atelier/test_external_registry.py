from __future__ import annotations

from pathlib import Path

from atelier.external_registry import planner_provider_environment
from atelier.models import ProjectConfig, ProjectSection


def test_planner_provider_environment_includes_github_repo() -> None:
    config_payload = ProjectConfig(
        project=ProjectSection(origin="github.com/acme/widgets")
    )
    env = planner_provider_environment(config_payload, Path("/repo"))
    assert env["ATELIER_EXTERNAL_PROVIDERS"] == "github"
    assert env["ATELIER_GITHUB_REPO"] == "acme/widgets"
