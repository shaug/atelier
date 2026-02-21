"""Contract tests for worker runtime public APIs."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable

PUBLIC_API_MODULES = (
    "atelier.worker.work_runtime_common",
    "atelier.worker.work_startup_runtime",
    "atelier.worker.work_finalization_state",
    "atelier.worker.work_finalization_integration",
    "atelier.worker.work_finalization_pipeline",
    "atelier.worker.work_finalization_reconcile",
)

FACADE_MODULES = (
    "atelier.worker.work_finalization_runtime",
    "atelier.worker.work_command_helpers",
)


def _iter_exports(module_name: str) -> Iterable[tuple[str, object]]:
    module = importlib.import_module(module_name)
    exports = getattr(module, "__all__", ())
    for name in exports:
        yield name, getattr(module, name)


def test_runtime_exports_do_not_use_private_names() -> None:
    module_names = (*PUBLIC_API_MODULES, *FACADE_MODULES)
    for module_name in module_names:
        for name, _ in _iter_exports(module_name):
            assert not name.startswith("_"), f"{module_name} exports private symbol {name!r}"


def test_runtime_public_functions_have_google_docstrings() -> None:
    for module_name in PUBLIC_API_MODULES:
        for name, exported in _iter_exports(module_name):
            if not inspect.isfunction(exported):
                continue
            doc = inspect.getdoc(exported)
            assert doc, f"{module_name}.{name} is missing a docstring"
            signature = inspect.signature(exported)
            has_inputs = any(
                parameter.name not in {"self", "cls"}
                and parameter.kind
                not in {
                    inspect.Parameter.VAR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                }
                for parameter in signature.parameters.values()
            )
            if has_inputs:
                assert "Args:" in doc, f"{module_name}.{name} docstring missing Args"
            assert "Returns:" in doc, f"{module_name}.{name} docstring missing Returns"
