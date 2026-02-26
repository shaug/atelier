import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import atelier.templates as templates


class TestInstalledTemplateComparison:
    def test_installed_template_matches_packaged_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                packaged = templates.agent_home_template()
                installed_path = data_dir / "templates" / "agent" / "AGENTS.md"
                installed_path.parent.mkdir(parents=True)
                installed_path.write_text(packaged, encoding="utf-8")

                assert templates.installed_template_modified("agent", "AGENTS.md") is False

    def test_installed_template_differs_from_packaged_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                installed_path = data_dir / "templates" / "agent" / "AGENTS.md"
                installed_path.parent.mkdir(parents=True)
                installed_path.write_text("custom agents\n", encoding="utf-8")

                assert templates.installed_template_modified("agent", "AGENTS.md") is True


class TestTemplateFallback:
    def test_prefer_installed_if_modified_uses_cache_when_packaged_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            installed_path = data_dir / "templates" / "AGENTS.worker.md.tmpl"
            installed_path.parent.mkdir(parents=True)
            installed_path.write_text("worker-template-cache\n", encoding="utf-8")

            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch(
                    "atelier.templates._read_template",
                    side_effect=FileNotFoundError("missing packaged template"),
                ),
                patch("atelier.templates._runtime_distribution_template_roots", return_value=()),
            ):
                result = templates.read_template_result(
                    "AGENTS.worker.md.tmpl",
                    prefer_installed_if_modified=True,
                )

        assert result.text == "worker-template-cache\n"
        assert result.source == "installed_cache_fallback"
        assert any("packaged default unreadable:" in attempt for attempt in result.attempts)

    def test_read_template_result_raises_when_all_sources_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch(
                    "atelier.templates._read_template",
                    side_effect=FileNotFoundError("missing packaged template"),
                ),
                patch("atelier.templates._runtime_distribution_template_roots", return_value=()),
            ):
                with pytest.raises(templates.TemplateReadError) as exc_info:
                    templates.read_template_result(
                        "AGENTS.worker.md.tmpl",
                        prefer_installed_if_modified=True,
                    )

        assert exc_info.value.template == "AGENTS.worker.md.tmpl"
        assert any("installed cache missing:" in attempt for attempt in exc_info.value.attempts)
        assert any("packaged default unreadable:" in attempt for attempt in exc_info.value.attempts)

    def test_packaged_template_falls_back_from_stale_worktree_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            stable_templates_root = root / "runtime" / "src" / "atelier" / "templates"
            stable_templates_root.mkdir(parents=True)
            packaged_template_path = stable_templates_root / "AGENTS.worker.md.tmpl"
            packaged_template_path.write_text("worker-template-packaged\n", encoding="utf-8")

            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch(
                    "atelier.templates._packaged_template_path",
                    return_value="/tmp/worktree/src/atelier/templates/AGENTS.worker.md.tmpl",
                ),
                patch(
                    "atelier.templates._read_template",
                    side_effect=FileNotFoundError("missing stale packaged template"),
                ),
                patch(
                    "atelier.templates._runtime_distribution_template_roots",
                    return_value=(("runtime_distribution_direct_url", stable_templates_root),),
                ),
            ):
                result = templates.read_template_result(
                    "AGENTS.worker.md.tmpl",
                    prefer_installed_if_modified=True,
                )

        assert result.text == "worker-template-packaged\n"
        assert result.source == "packaged_default"
        assert any(
            "packaged default unreadable: "
            "/tmp/worktree/src/atelier/templates/AGENTS.worker.md.tmpl "
            "[origin=runtime_package_resources]" in attempt
            for attempt in result.attempts
        )
        assert any(
            f"packaged default loaded: {packaged_template_path} "
            "[origin=runtime_distribution_direct_url]" in attempt
            for attempt in result.attempts
        )
