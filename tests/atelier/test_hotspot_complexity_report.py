from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "hotspot_complexity_report.py"
    spec = importlib.util.spec_from_file_location("hotspot_complexity_report", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_guardrail_check_passes_current_hotspots() -> None:
    module = _load_script_module()
    repo_root = Path(__file__).resolve().parents[2]

    metrics, violations = module.run_guardrail_check(repo_root=repo_root)

    assert len(metrics) == len(module.HOTSPOT_BUDGETS)
    assert isinstance(violations, list)


def test_run_guardrail_check_reports_budget_regression() -> None:
    module = _load_script_module()
    repo_root = Path(__file__).resolve().parents[2]
    baseline = module.HOTSPOT_BUDGETS[0]
    strict_budget = module.HotspotBudget(
        module_path=baseline.module_path,
        function_name=baseline.function_name,
        max_span=1,
        max_complexity=1,
    )

    _metrics, violations = module.run_guardrail_check(repo_root=repo_root, budgets=[strict_budget])

    assert any("exceeds budget" in item for item in violations)


def test_cli_check_mode_succeeds_for_current_repository() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "hotspot_complexity_report.py"
    result = subprocess.run(
        [sys.executable, str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Hotspot complexity baseline report" in result.stdout
