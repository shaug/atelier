#!/usr/bin/env python3
"""Report and enforce complexity guardrails for hotspot functions.

This script provides a deterministic, stdlib-only baseline for line span and
cyclomatic-style decision complexity on known hotspot functions. Use
``--check`` to fail when hotspots exceed the configured budgets.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class HotspotBudget:
    """Budget for one hotspot function.

    Args:
        module_path: Path to a Python module, relative to repository root.
        function_name: Top-level function name to inspect.
        max_span: Maximum allowed source line span.
        max_complexity: Maximum allowed cyclomatic-style complexity.
    """

    module_path: str
    function_name: str
    max_span: int
    max_complexity: int


@dataclass(frozen=True)
class HotspotMetric:
    """Observed metrics for one hotspot function.

    Args:
        budget: Budget definition for this hotspot.
        observed_span: Observed source line span.
        observed_complexity: Observed cyclomatic-style complexity.
    """

    budget: HotspotBudget
    observed_span: int
    observed_complexity: int


HOTSPOT_BUDGETS: tuple[HotspotBudget, ...] = (
    HotspotBudget(
        module_path="src/atelier/beads.py",
        function_name="run_bd_command",
        max_span=150,
        max_complexity=40,
    ),
    HotspotBudget(
        module_path="src/atelier/beads.py",
        function_name="_raw_bd_json",
        max_span=110,
        max_complexity=40,
    ),
    HotspotBudget(
        module_path="src/atelier/beads.py",
        function_name="claim_epic",
        max_span=120,
        max_complexity=36,
    ),
    HotspotBudget(
        module_path="src/atelier/worker/session/runner.py",
        function_name="run_worker_once",
        max_span=800,
        max_complexity=132,
    ),
    HotspotBudget(
        module_path="src/atelier/worker/session/startup.py",
        function_name="run_startup_contract_service",
        max_span=610,
        max_complexity=115,
    ),
    HotspotBudget(
        module_path="src/atelier/worker/finalize_pipeline.py",
        function_name="run_finalize_pipeline",
        max_span=470,
        max_complexity=80,
    ),
    HotspotBudget(
        module_path="src/atelier/worker/reconcile.py",
        function_name="reconcile_blocked_merged_changesets",
        max_span=440,
        max_complexity=95,
    ),
)

_DECISION_NODES: tuple[type[ast.AST], ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.ExceptHandler,
    ast.Assert,
)


def _load_function_node(
    module_path: Path, function_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Load a top-level function node from a module.

    Args:
        module_path: Absolute path to the module to inspect.
        function_name: Top-level function name to locate.

    Returns:
        The matching function node.

    Raises:
        ValueError: If the module or function cannot be parsed/found.
    """

    try:
        source = module_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"Missing module: {module_path}") from exc

    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse module {module_path}: {exc}") from exc

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node

    raise ValueError(f"Function {function_name!r} was not found in {module_path}")


def _cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Compute cyclomatic-style complexity.

    Args:
        node: Function AST node.

    Returns:
        Baseline complexity where each decision path increments the score.
    """

    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            complexity += max(0, len(child.values) - 1)
            continue
        if isinstance(child, ast.Try):
            complexity += len(child.handlers)
            complexity += int(bool(child.orelse))
            complexity += int(bool(child.finalbody))
            continue
        if isinstance(child, ast.Match):
            complexity += len(child.cases)
            continue
        if isinstance(child, _DECISION_NODES):
            complexity += 1
    return complexity


def collect_hotspot_metrics(
    repo_root: Path,
    budgets: Sequence[HotspotBudget] = HOTSPOT_BUDGETS,
) -> list[HotspotMetric]:
    """Collect span and complexity metrics for hotspot functions.

    Args:
        repo_root: Absolute repository root.
        budgets: Hotspot budget definitions.

    Returns:
        One metric row for every budget entry.

    Raises:
        ValueError: If a target module/function cannot be inspected.
    """

    metrics: list[HotspotMetric] = []
    for budget in budgets:
        node = _load_function_node(repo_root / budget.module_path, budget.function_name)
        if node.end_lineno is None:
            raise ValueError(
                f"Function {budget.function_name!r} in {budget.module_path} is missing end line info"
            )
        span = node.end_lineno - node.lineno + 1
        complexity = _cyclomatic_complexity(node)
        metrics.append(
            HotspotMetric(
                budget=budget,
                observed_span=span,
                observed_complexity=complexity,
            )
        )
    return metrics


def evaluate_hotspot_budgets(metrics: Sequence[HotspotMetric]) -> list[str]:
    """Evaluate guardrail budget violations.

    Args:
        metrics: Observed hotspot measurements.

    Returns:
        Human-readable violations. Empty list when all budgets pass.
    """

    violations: list[str] = []
    for metric in metrics:
        budget = metric.budget
        identifier = f"{budget.module_path}:{budget.function_name}"
        if metric.observed_span > budget.max_span:
            violations.append(
                f"{identifier} span {metric.observed_span} exceeds budget {budget.max_span}"
            )
        if metric.observed_complexity > budget.max_complexity:
            violations.append(
                f"{identifier} complexity {metric.observed_complexity} exceeds "
                f"budget {budget.max_complexity}"
            )
    return violations


def run_guardrail_check(
    repo_root: Path,
    budgets: Sequence[HotspotBudget] = HOTSPOT_BUDGETS,
) -> tuple[list[HotspotMetric], list[str]]:
    """Collect metrics and evaluate budgets.

    Args:
        repo_root: Absolute repository root.
        budgets: Hotspot budget definitions.

    Returns:
        Tuple of ``(metrics, violations)``.
    """

    metrics = collect_hotspot_metrics(repo_root=repo_root, budgets=budgets)
    violations = evaluate_hotspot_budgets(metrics)
    return metrics, violations


def _render_report(metrics: Sequence[HotspotMetric], violations: Sequence[str]) -> str:
    """Render report text for CLI output.

    Args:
        metrics: Observed hotspot metrics.
        violations: Budget violations.

    Returns:
        Multi-line report text.
    """

    lines = ["Hotspot complexity baseline report", ""]
    lines.append(
        "Function".ljust(85)
        + "Span".rjust(8)
        + "Budget".rjust(8)
        + "CC".rjust(8)
        + "Budget".rjust(8)
    )
    lines.append("-" * 117)
    for metric in metrics:
        budget = metric.budget
        identifier = f"{budget.module_path}:{budget.function_name}"
        lines.append(
            identifier.ljust(85)
            + str(metric.observed_span).rjust(8)
            + str(budget.max_span).rjust(8)
            + str(metric.observed_complexity).rjust(8)
            + str(budget.max_complexity).rjust(8)
        )
    lines.append("")
    if violations:
        lines.append("Guardrail violations:")
        for violation in violations:
            lines.append(f"- {violation}")
    else:
        lines.append("All hotspot guardrails are satisfied.")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Report and enforce hotspot complexity guardrails."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to inspect (defaults to this script's parent).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero when a guardrail is violated.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the CLI entrypoint.

    Returns:
        Process exit code.
    """

    args = _parse_args()
    metrics, violations = run_guardrail_check(repo_root=args.repo_root)
    print(_render_report(metrics, violations))
    if args.check and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
