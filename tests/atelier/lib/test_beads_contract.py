from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from atelier.lib.beads import DEFAULT_COMPATIBILITY_POLICY, SupportedOperation

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_FIXTURE_PATH = FIXTURES_DIR / "beads_client_contract_v1.json"
CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"
ADOPTION_GUIDE_PATH = REPO_ROOT / "docs" / "beads-adoption-guide.md"
README_PATH = REPO_ROOT / "README.md"

_OPERATION_METHODS = {
    SupportedOperation.INSPECT_ENVIRONMENT: "inspect_environment",
    SupportedOperation.SHOW: "show",
    SupportedOperation.LIST: "list",
    SupportedOperation.READY: "ready",
    SupportedOperation.CREATE: "create",
    SupportedOperation.UPDATE: "update",
    SupportedOperation.CLOSE: "close",
    SupportedOperation.DEPENDENCY_ADD: "add_dependency",
    SupportedOperation.DEPENDENCY_REMOVE: "remove_dependency",
}


class OperationFixture(TypedDict):
    operation: str
    method: str
    output_mode: str
    required_capabilities: list[str]


class DownstreamContractFixture(TypedDict):
    role: str
    rule: str


class ContractFixture(TypedDict):
    minimum_version: str
    maximum_version_exclusive: str | None
    capabilities: list[str]
    operations: list[OperationFixture]
    unsupported_surface: list[str]
    downstream_contract: dict[str, DownstreamContractFixture]


def _load_contract_fixture() -> ContractFixture:
    return json.loads(CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_beads_contract_fixture_matches_default_policy() -> None:
    payload = _load_contract_fixture()

    assert payload["minimum_version"] == str(DEFAULT_COMPATIBILITY_POLICY.minimum_version)
    assert payload["maximum_version_exclusive"] is None
    assert payload["capabilities"] == [
        rule.capability.value for rule in DEFAULT_COMPATIBILITY_POLICY.capability_rules
    ]
    assert payload["operations"] == [
        {
            "operation": contract.operation.value,
            "method": _OPERATION_METHODS[contract.operation],
            "output_mode": contract.output_mode.value,
            "required_capabilities": [
                capability.value for capability in contract.required_capabilities
            ],
        }
        for contract in DEFAULT_COMPATIBILITY_POLICY.operations
    ]


def test_contract_doc_publishes_supported_inventory_and_downstream_rules() -> None:
    payload = _load_contract_fixture()
    content = CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "Beads Client v1 Contract" in content
    assert payload["minimum_version"] in content
    for operation in payload["operations"]:
        assert operation["operation"] in content
        assert operation["method"] in content
    for unsupported_command in payload["unsupported_surface"]:
        assert unsupported_command in content
    for downstream_id in payload["downstream_contract"]:
        assert downstream_id in content


def test_readme_points_to_the_published_beads_contract() -> None:
    content = README_PATH.read_text(encoding="utf-8")

    assert "`bd` `>= 0.56.1`" in content
    assert "docs/beads-client-contract.md" in content


def test_readme_and_docs_publish_the_beads_adoption_boundary() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    guide = ADOPTION_GUIDE_PATH.read_text(encoding="utf-8")
    contract = CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "docs/beads-adoption-guide.md" in readme
    assert "atelier.lib.beads" in guide
    assert "atelier.testing.beads" in guide
    assert "at-njpt4" in guide
    assert "docs/beads-adoption-guide.md" in contract
