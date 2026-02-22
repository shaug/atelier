from __future__ import annotations

from pathlib import Path

from atelier.external_registry import (
    discover_ticket_provider_manifests,
    planner_provider_environment,
    resolve_planner_provider,
)
from atelier.models import ProjectConfig, ProjectSection


def test_planner_provider_environment_includes_github_repo() -> None:
    config_payload = ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets"))
    env = planner_provider_environment(config_payload, Path("/repo"))
    assert env["ATELIER_EXTERNAL_PROVIDERS"] == "github"
    assert env["ATELIER_EXTERNAL_PROVIDER"] == "github"
    assert env["ATELIER_EXTERNAL_AUTO_EXPORT"] == "0"
    assert env["ATELIER_GITHUB_REPO"] == "acme/widgets"


def test_planner_provider_environment_includes_repo_beads(
    tmp_path: Path,
) -> None:
    (tmp_path / ".beads").mkdir()
    config_payload = ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets"))
    env = planner_provider_environment(config_payload, tmp_path)
    assert env["ATELIER_EXTERNAL_PROVIDERS"] == "beads,github"
    assert env["ATELIER_EXTERNAL_PROVIDER"] == "github"
    assert env["ATELIER_EXTERNAL_AUTO_EXPORT"] == "0"
    assert env["ATELIER_GITHUB_REPO"] == "acme/widgets"


def test_planner_provider_environment_sets_auto_export_when_enabled() -> None:
    config_payload = ProjectConfig(
        project=ProjectSection(
            origin="github.com/acme/widgets",
            provider="github",
            auto_export_new=True,
        )
    )
    env = planner_provider_environment(config_payload, Path("/repo"))
    assert env["ATELIER_EXTERNAL_AUTO_EXPORT"] == "1"


def test_discover_ticket_provider_manifests_from_project_skills(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "project-data"
    skills_dir = project_data_dir / "skills"
    github_dir = skills_dir / "github-issues"
    github_dir.mkdir(parents=True)
    (github_dir / "SKILL.md").write_text(
        "---\nname: github-issues\ndescription: test\n---\n\n# GitHub Issues\n",
        encoding="utf-8",
    )
    invalid_dir = skills_dir / "broken-provider"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "SKILL.md").write_text("# Unknown\n", encoding="utf-8")

    manifests = discover_ticket_provider_manifests(
        agent_name="aider",
        project_data_dir=project_data_dir,
    )
    assert [item.provider for item in manifests] == ["github"]


def test_discover_ticket_provider_from_legacy_skill_name(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "project-data"
    linear_dir = project_data_dir / "skills" / "linear"
    linear_dir.mkdir(parents=True)
    (linear_dir / "SKILL.md").write_text(
        "---\nname: linear\ndescription: test\n---\n\n# Linear\n",
        encoding="utf-8",
    )

    manifests = discover_ticket_provider_manifests(
        agent_name="aider",
        project_data_dir=project_data_dir,
    )
    assert [item.provider for item in manifests] == ["linear"]


def test_resolve_planner_provider_prefers_configured_provider(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "project-data"
    skills_dir = project_data_dir / "skills" / "github-issues"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: github-issues\ndescription: test\n---\n\n# GitHub Issues\n",
        encoding="utf-8",
    )
    config_payload = ProjectConfig(
        project=ProjectSection(origin="github.com/acme/widgets", provider="github")
    )

    resolution = resolve_planner_provider(
        config_payload,
        tmp_path,
        agent_name="codex",
        project_data_dir=project_data_dir,
        interactive=False,
    )
    assert resolution.selected_provider == "github"
    assert "github" in resolution.available_providers


def test_resolve_planner_provider_prompts_when_multiple(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "project-data"
    skills_dir = project_data_dir / "skills"
    github_dir = skills_dir / "github-issues"
    github_dir.mkdir(parents=True)
    (github_dir / "SKILL.md").write_text("# GitHub Issues\n", encoding="utf-8")
    linear_dir = skills_dir / "linear"
    linear_dir.mkdir(parents=True)
    (linear_dir / "SKILL.md").write_text("# Linear\n", encoding="utf-8")

    selected: dict[str, object] = {}

    def chooser(text: str, choices: list[str] | tuple[str, ...], default: str | None) -> str:
        selected["text"] = text
        selected["choices"] = list(choices)
        selected["default"] = default
        return "linear"

    resolution = resolve_planner_provider(
        ProjectConfig(project=ProjectSection(origin="github.com/acme/widgets")),
        tmp_path,
        agent_name="codex",
        project_data_dir=project_data_dir,
        interactive=True,
        chooser=chooser,
    )

    assert selected["text"] == "External provider"
    assert resolution.selected_provider == "linear"
    assert "github" in resolution.available_providers
    assert "linear" in resolution.available_providers
