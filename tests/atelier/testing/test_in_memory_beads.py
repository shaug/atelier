from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.lib.beads import (
    BeadsCommandResult,
    IssueRecord,
    decode_help_output,
    decode_version_output,
)
from atelier.testing.beads import (
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    SUPPORTED_GLOBAL_FLAGS,
    CommandEnvelope,
    InMemoryBeadsCommandBackend,
    InMemoryBeadsDispatcher,
    IssueFixtureBuilder,
    normalize_invocation,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "in-memory-beads-command-contract.md"
CLIENT_CONTRACT_DOC_PATH = REPO_ROOT / "docs" / "beads-client-contract.md"


def test_contract_docs_publish_route_inventory() -> None:
    content = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    client_contract = CLIENT_CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert "In-Memory Beads Command Contract" in content
    assert "source contract" in content
    assert IN_MEMORY_BEADS_VERSION in content
    assert "- `core-issues` (Tier 0): routes `show`, `list`, `ready`, `create`," in content
    assert "- `runtime-admin` (Tier 3): routes `stats`, `doctor`, `migrate`," in content
    assert "`--json` routes: all documented routes" in content
    assert "`--json` routes: `dolt show`," in content
    assert "`vc status`" in content
    for flag in SUPPORTED_GLOBAL_FLAGS:
        assert flag in content
    for route in DOCUMENTED_COMMAND_ROUTES:
        assert route.command_label in content
        assert route.family_id in content
    assert "docs/in-memory-beads-command-contract.md" in client_contract


def test_documented_routes_cover_each_planned_command_family() -> None:
    assert {route.family_id for route in DOCUMENTED_COMMAND_ROUTES} == {
        "core-issues",
        "dependency-edges",
        "ownership-slots",
        "startup-config",
        "runtime-admin",
    }


def test_dispatcher_protocol_and_version_help_are_client_compatible() -> None:
    dispatcher = InMemoryBeadsDispatcher()

    assert isinstance(dispatcher, InMemoryBeadsCommandBackend)

    version_result = dispatcher.run(["bd", "--version"])
    help_result = dispatcher.run(["bd", "show", "--help"])

    assert str(decode_version_output(version_result)) == IN_MEMORY_BEADS_VERSION
    normalized_help = BeadsCommandResult(
        argv=tuple(str(token) for token in help_result.args),
        returncode=help_result.returncode,
        stdout=help_result.stdout,
        stderr=help_result.stderr,
    )
    assert decode_help_output(normalized_help).supports_json_output is True


def test_dispatcher_strips_supported_global_flags_before_matching() -> None:
    builder = IssueFixtureBuilder()

    def core_handler(route, invocation):  # type: ignore[no-untyped-def]
        del invocation
        assert route.command == ("show",)
        return CommandEnvelope.json_payload([builder.issue(7)])

    dispatcher = InMemoryBeadsDispatcher(family_handlers={"core-issues": core_handler})
    result = dispatcher.run(["bd", "--db", "/tmp/beads.db", "--readonly", "show", "at-7", "--json"])

    issue = IssueRecord.model_validate(json.loads(result.stdout)[0])

    assert issue.id == "at-7"


@pytest.mark.parametrize(
    ("argv", "family_id"),
    [
        (["bd", "show", "at-1", "--json"], "core-issues"),
        (["bd", "dep", "add", "at-2", "at-1", "--json"], "dependency-edges"),
        (["bd", "slot", "set", "at-agent", "hook", "at-epic"], "ownership-slots"),
        (["bd", "config", "set", "issue_prefix", "at"], "startup-config"),
        (["bd", "dolt", "commit"], "runtime-admin"),
    ],
)
def test_dispatcher_marks_default_family_handlers_as_explicitly_unimplemented(
    argv: list[str],
    family_id: str,
) -> None:
    result = InMemoryBeadsDispatcher().run(argv)

    assert result.returncode == DEFAULT_UNIMPLEMENTED_RETURN_CODE
    assert family_id in result.stderr
    assert "not implemented yet" in result.stderr


def test_issue_fixture_builder_is_deterministic_and_payload_compatible() -> None:
    builder = IssueFixtureBuilder()
    first = builder.issue(
        5,
        labels=("atelier", "changeset", "atelier"),
        parent=1,
        dependencies=(2,),
        metadata={"claimed_by": "agent-1"},
        extra_fields={"future_field": {"nested": True}},
    )

    assert first == builder.issue(
        5,
        labels=("atelier", "changeset", "atelier"),
        parent=1,
        dependencies=(2,),
        metadata={"claimed_by": "agent-1"},
        extra_fields={"future_field": {"nested": True}},
    )

    issue = IssueRecord.model_validate(first)

    assert issue.id == "at-5"
    assert issue.labels == ("atelier", "changeset")
    assert issue.parent and issue.parent.id == "at-1"
    assert issue.dependencies[0].id == "at-2"
    assert issue.extra_fields["future_field"] == {"nested": True}


def test_normalize_invocation_preserves_command_and_global_tokens() -> None:
    invocation = normalize_invocation(
        ["bd", "--db=/tmp/beads.db", "--sandbox", "vc", "status", "--json"]
    )

    assert invocation.global_tokens == ("--db=/tmp/beads.db", "--sandbox")
    assert invocation.command_tokens == ("vc", "status", "--json")
    assert invocation.requests_json is True
