from __future__ import annotations

import ast
import difflib
import json
import re
from pathlib import Path

_DIRECT_BEADS_REFERENCE = re.compile(r"\batelier\.beads\.")
_INVENTORY_PATH = Path("docs/beads-facade-inventory.json")
_TRACKED_GLOBS = ("src/**/*.py", "tests/**/*.py")
_EXPECTED_FOLLOW_ONS = {"at-rhxbc.2", "at-rhxbc.3", "at-rhxbc.4"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sorted_imports(imports: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        imports,
        key=lambda value: (
            str(value.get("kind") or ""),
            str(value.get("module") or ""),
            str(value.get("name") or ""),
            str(value.get("alias") or ""),
        ),
    )


def _collect_direct_beads_usage(repo_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    candidates = sorted(
        {path for pattern in _TRACKED_GLOBS for path in repo_root.glob(pattern) if path.is_file()}
    )
    for path in candidates:
        relative_path = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=relative_path)
        imports: list[dict[str, object]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "atelier.beads":
                        imports.append(
                            {
                                "kind": "import",
                                "module": alias.name,
                                "alias": alias.asname,
                            }
                        )
            if isinstance(node, ast.ImportFrom) and node.module == "atelier":
                for alias in node.names:
                    if alias.name == "beads":
                        imports.append(
                            {
                                "kind": "from",
                                "module": "atelier",
                                "name": alias.name,
                                "alias": alias.asname,
                            }
                        )
        dotted_refs = len(_DIRECT_BEADS_REFERENCE.findall(text))
        if imports or dotted_refs:
            records.append(
                {
                    "path": relative_path,
                    "imports": _sorted_imports(imports),
                    "dotted_refs": dotted_refs,
                }
            )
    return records


def _load_inventory(repo_root: Path) -> dict[str, object]:
    return json.loads((repo_root / _INVENTORY_PATH).read_text(encoding="utf-8"))


def _flatten_inventory(payload: dict[str, object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for domain in payload.get("concern_domains", []):
        if not isinstance(domain, dict):
            continue
        for call_site in domain.get("call_sites", []):
            if not isinstance(call_site, dict):
                continue
            records.append(
                {
                    "path": call_site["path"],
                    "imports": _sorted_imports(list(call_site.get("imports", []))),
                    "dotted_refs": call_site["dotted_refs"],
                }
            )
    return sorted(records, key=lambda value: str(value["path"]))


def test_beads_facade_inventory_matches_repo_usage() -> None:
    repo_root = _repo_root()
    inventory = _load_inventory(repo_root)
    expected = _flatten_inventory(inventory)
    actual = _collect_direct_beads_usage(repo_root)

    if actual != expected:
        expected_text = json.dumps(expected, indent=2, sort_keys=True)
        actual_text = json.dumps(actual, indent=2, sort_keys=True)
        diff = "\n".join(
            difflib.unified_diff(
                expected_text.splitlines(),
                actual_text.splitlines(),
                fromfile="docs/beads-facade-inventory.json",
                tofile="repo scan",
                lineterm="",
            )
        )
        raise AssertionError(
            "direct atelier.beads usage drifted from the checked-in inventory.\n"
            "Update the inventory only when intentionally draining or relocating "
            "the retained facade surface.\n"
            f"{diff}"
        )


def test_beads_facade_inventory_records_follow_on_drain_map() -> None:
    inventory = _load_inventory(_repo_root())
    domains = inventory.get("concern_domains", [])
    assert isinstance(domains, list)
    seen_paths: set[str] = set()
    for domain in domains:
        assert isinstance(domain, dict)
        assert domain.get("name")
        assert domain.get("summary")
        assert domain.get("follow_on_changeset") in _EXPECTED_FOLLOW_ONS
        call_sites = domain.get("call_sites", [])
        assert isinstance(call_sites, list)
        assert call_sites
        for call_site in call_sites:
            assert isinstance(call_site, dict)
            path = str(call_site.get("path") or "")
            assert path
            assert path not in seen_paths
            seen_paths.add(path)
