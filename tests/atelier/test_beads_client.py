from __future__ import annotations

import pytest
from pydantic import ValidationError

from atelier.beads_client import (
    DEFAULT_COMPATIBILITY_POLICY,
    AsyncBeadsClient,
    BeadsCapability,
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    BeadsTransport,
    CapabilityMismatchError,
    CapabilityRule,
    CompatibilityPolicy,
    IssueRecord,
    OperationContract,
    OperationOutputMode,
    SemanticVersion,
    SupportedOperation,
    UnsupportedVersionError,
    UpdateIssueRequest,
)


def test_issue_record_preserves_unknown_fields() -> None:
    record = IssueRecord.model_validate(
        {
            "id": "at-1",
            "labels": ["atelier", "changeset", "atelier"],
            "parent": {"id": "at-epic"},
            "dependencies": ["at-0"],
            "future_field": {"nested": True},
        }
    )

    assert record.labels == ("atelier", "changeset")
    assert record.parent and record.parent.id == "at-epic"
    assert record.dependencies[0].id == "at-0"
    assert record.extra_fields["future_field"] == {"nested": True}


def test_issue_record_rejects_known_field_type_mismatch() -> None:
    with pytest.raises(ValidationError, match="id"):
        IssueRecord.model_validate({"id": 7})


def test_update_request_requires_a_field_change() -> None:
    with pytest.raises(ValidationError, match="at least one field change"):
        UpdateIssueRequest(issue_id="at-1")


def test_compatibility_policy_rejects_unsupported_version() -> None:
    environment = BeadsEnvironment(
        version=SemanticVersion(major=0, minor=56, patch=0),
        capabilities=[BeadsCapability.VERSION_REPORTING],
    )

    with pytest.raises(UnsupportedVersionError, match="requires >= 0.56.1"):
        DEFAULT_COMPATIBILITY_POLICY.assert_environment_supports(environment)


def test_compatibility_policy_rejects_missing_capability() -> None:
    environment = BeadsEnvironment(
        version=SemanticVersion(major=0, minor=56, patch=1),
        capabilities=[BeadsCapability.VERSION_REPORTING],
    )

    with pytest.raises(CapabilityMismatchError, match="issue-json"):
        DEFAULT_COMPATIBILITY_POLICY.assert_environment_supports(
            environment,
            operation=SupportedOperation.SHOW,
        )


def test_compatibility_policy_supports_explicit_capability_ceiling() -> None:
    policy = CompatibilityPolicy(
        minimum_version=SemanticVersion(major=0, minor=56, patch=1),
        capability_rules=(
            CapabilityRule(
                capability=BeadsCapability.ISSUE_JSON,
                maximum_version_exclusive=SemanticVersion(major=0, minor=99, patch=0),
            ),
        ),
        operations=(
            OperationContract(
                operation=SupportedOperation.SHOW,
                output_mode=OperationOutputMode.JSON_REQUIRED,
                required_capabilities=(BeadsCapability.ISSUE_JSON,),
            ),
        ),
    )

    with pytest.raises(CapabilityMismatchError, match="supported capability window"):
        policy.assert_environment_supports(
            BeadsEnvironment(
                version=SemanticVersion(major=0, minor=99, patch=0),
                capabilities=[BeadsCapability.ISSUE_JSON],
            ),
            operation=SupportedOperation.SHOW,
        )


class _FakeTransport:
    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        return BeadsCommandResult(argv=request.argv, returncode=0, stdout="[]", stderr="")


class _FakeClient:
    compatibility_policy = DEFAULT_COMPATIBILITY_POLICY

    async def inspect_environment(self) -> BeadsEnvironment:
        capabilities = [rule.capability for rule in DEFAULT_COMPATIBILITY_POLICY.capability_rules]
        return BeadsEnvironment(
            version=SemanticVersion(major=0, minor=56, patch=1),
            capabilities=capabilities,
        )

    async def show(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")

    async def list(self, request: object) -> tuple[IssueRecord, ...]:
        del request
        return (IssueRecord(id="at-1"),)

    async def ready(self, request: object) -> tuple[IssueRecord, ...]:
        del request
        return ()

    async def create(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")

    async def update(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")

    async def close(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")

    async def add_dependency(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")

    async def remove_dependency(self, request: object) -> IssueRecord:
        del request
        return IssueRecord(id="at-1")


def test_protocols_are_runtime_checkable() -> None:
    assert isinstance(_FakeTransport(), BeadsTransport)
    assert isinstance(_FakeClient(), AsyncBeadsClient)
