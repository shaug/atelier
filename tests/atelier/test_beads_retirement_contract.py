from __future__ import annotations

import ast
import difflib
import json
from pathlib import Path

_CONTRACT_PATH = Path("docs/beads-facade-contract.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collect_public_surface(repo_root: Path) -> list[str]:
    source = (repo_root / "src" / "atelier" / "beads.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/atelier/beads.py")
    symbols = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    return sorted(symbols)


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


def test_beads_retirement_contract_matches_public_surface() -> None:
    repo_root = _repo_root()
    contract = _load_contract(repo_root)
    expected = _flatten_contract(contract)
    actual = _collect_public_surface(repo_root)

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
            "public atelier.beads surface drifted from the retirement contract.\n"
            "Update the contract only when intentionally retaining or pruning facade API.\n"
            f"{diff}"
        )


def test_beads_retirement_contract_keeps_dead_symbols_retired() -> None:
    repo_root = _repo_root()
    contract = _load_contract(repo_root)
    retired = contract.get("retired_symbols", [])
    assert isinstance(retired, list)
    public_surface = set(_collect_public_surface(repo_root))
    for symbol in retired:
        assert isinstance(symbol, str)
        assert symbol not in public_surface
