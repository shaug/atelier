from __future__ import annotations

import ast
import difflib
import json
from pathlib import Path

_CONTRACT_PATH = Path("docs/beads-facade-contract.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _names_from_assignment_target(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.List, ast.Tuple)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_names_from_assignment_target(element))
        return names
    return []


def _collect_public_module_globals(repo_root: Path) -> list[str]:
    source = (repo_root / "src" / "atelier" / "beads.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/atelier/beads.py")
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                symbols.add(alias.asname or alias.name.split(".")[-1])
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                symbols.add(alias.asname or alias.name.split(".")[-1])
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                symbols.update(_names_from_assignment_target(target))
            continue
        if isinstance(node, ast.AnnAssign):
            symbols.update(_names_from_assignment_target(node.target))
    return sorted(symbol for symbol in symbols if not symbol.startswith("_"))


def _load_contract(repo_root: Path) -> dict[str, object]:
    return json.loads((repo_root / _CONTRACT_PATH).read_text(encoding="utf-8"))


def _flatten_contract(payload: dict[str, object]) -> list[str]:
    retained_surface = payload.get("retained_surface", [])
    assert isinstance(retained_surface, list)
    flattened: list[str] = []
    for domain in retained_surface:
        assert isinstance(domain, dict)
        assert domain.get("name")
        assert domain.get("summary")
        symbols = domain.get("symbols", [])
        assert isinstance(symbols, list)
        assert symbols
        for symbol in symbols:
            assert isinstance(symbol, str)
            assert symbol
            flattened.append(symbol)
    return sorted(flattened)


def _contract_public_module_globals(payload: dict[str, object]) -> list[str]:
    public_module_globals = payload.get("public_module_globals", [])
    assert isinstance(public_module_globals, list)
    flattened: list[str] = []
    for symbol in public_module_globals:
        assert isinstance(symbol, str)
        assert symbol
        flattened.append(symbol)
    return sorted(flattened)


def test_beads_retirement_contract_matches_public_module_globals() -> None:
    repo_root = _repo_root()
    contract = _load_contract(repo_root)
    expected = _contract_public_module_globals(contract)
    actual = _collect_public_module_globals(repo_root)

    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                json.dumps(expected, indent=2).splitlines(),
                json.dumps(actual, indent=2).splitlines(),
                fromfile="docs/beads-facade-contract.json",
                tofile="src/atelier/beads.py",
                lineterm="",
            )
        )
        raise AssertionError(
            "public atelier.beads module globals drifted from the retirement contract.\n"
            "Update the contract only when intentionally changing the exposed module namespace.\n"
            f"{diff}"
        )


def test_beads_retirement_contract_retained_surface_is_public() -> None:
    repo_root = _repo_root()
    contract = _load_contract(repo_root)
    retained = _flatten_contract(contract)
    public_module_globals = set(_contract_public_module_globals(contract))
    for symbol in retained:
        assert symbol in public_module_globals


def test_beads_retirement_contract_keeps_dead_symbols_retired() -> None:
    repo_root = _repo_root()
    contract = _load_contract(repo_root)
    retired = contract.get("retired_symbols", [])
    assert isinstance(retired, list)
    public_surface = set(_collect_public_module_globals(repo_root))
    for symbol in retired:
        assert isinstance(symbol, str)
        assert symbol not in public_surface
