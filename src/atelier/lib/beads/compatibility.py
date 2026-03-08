"""Compatibility policy for supported ``bd`` versions and capabilities."""

from __future__ import annotations

from pydantic import field_validator

from .errors import CapabilityMismatchError, UnsupportedOperationError, UnsupportedVersionError
from .models import (
    BeadsCapability,
    BeadsEnvironment,
    BeadsModel,
    NonBlankStr,
    OperationOutputMode,
    SemanticVersion,
    SupportedOperation,
)


class CapabilityRule(BeadsModel):
    """Version window for a required capability."""

    capability: BeadsCapability
    minimum_version: SemanticVersion | None = None
    maximum_version_exclusive: SemanticVersion | None = None
    notes: NonBlankStr | None = None

    def supports(self, version: SemanticVersion) -> bool:
        """Return whether the rule allows the given version."""

        if self.minimum_version and version < self.minimum_version:
            return False
        if self.maximum_version_exclusive and version >= self.maximum_version_exclusive:
            return False
        return True


class OperationContract(BeadsModel):
    """Compatibility contract for a supported operation."""

    operation: SupportedOperation
    output_mode: OperationOutputMode
    required_capabilities: tuple[BeadsCapability, ...] = ()

    @field_validator("required_capabilities")
    @classmethod
    def _dedupe_capabilities(
        cls,
        value: tuple[BeadsCapability, ...],
    ) -> tuple[BeadsCapability, ...]:
        seen: set[BeadsCapability] = set()
        return tuple(item for item in value if not (item in seen or seen.add(item)))


class CompatibilityPolicy(BeadsModel):
    """Bounded compatibility policy for the Beads client."""

    minimum_version: SemanticVersion
    maximum_version_exclusive: SemanticVersion | None = None
    capability_rules: tuple[CapabilityRule, ...] = ()
    operations: tuple[OperationContract, ...] = ()

    def operation_contract(self, operation: SupportedOperation) -> OperationContract:
        """Return the declared contract for one supported operation."""

        for contract in self.operations:
            if contract.operation == operation:
                return contract
        raise UnsupportedOperationError(f"unsupported beads operation: {operation.value}")

    def assert_environment_supports(
        self,
        environment: BeadsEnvironment,
        *,
        operation: SupportedOperation | None = None,
    ) -> None:
        """Validate that an environment satisfies this compatibility policy."""

        version = environment.version
        if version < self.minimum_version:
            raise UnsupportedVersionError(
                f"unsupported bd version {version}; requires >= {self.minimum_version}"
            )
        if self.maximum_version_exclusive and version >= self.maximum_version_exclusive:
            raise UnsupportedVersionError(
                f"unsupported bd version {version}; requires < {self.maximum_version_exclusive}"
            )
        if operation is None:
            return

        contract = self.operation_contract(operation)
        available = set(environment.capabilities)
        missing = tuple(cap for cap in contract.required_capabilities if cap not in available)
        if missing:
            joined = ", ".join(cap.value for cap in missing)
            raise CapabilityMismatchError(
                f"bd is missing required capabilities for {operation.value}: {joined}"
            )

        rules = {rule.capability: rule for rule in self.capability_rules}
        blocked = tuple(
            cap
            for cap in contract.required_capabilities
            if cap in rules and not rules[cap].supports(version)
        )
        if blocked:
            joined = ", ".join(cap.value for cap in blocked)
            raise CapabilityMismatchError(
                f"bd {version} is outside the supported capability window for "
                f"{operation.value}: {joined}"
            )


DEFAULT_MINIMUM_BD_VERSION = SemanticVersion(major=0, minor=56, patch=1)
_READ_CAPS = (BeadsCapability.VERSION_REPORTING, BeadsCapability.ISSUE_JSON)
_WRITE_CAPS = (BeadsCapability.VERSION_REPORTING, BeadsCapability.ISSUE_MUTATION)
_DEP_CAPS = (
    BeadsCapability.VERSION_REPORTING,
    BeadsCapability.ISSUE_JSON,
    BeadsCapability.DEPENDENCY_MUTATION,
)

DEFAULT_COMPATIBILITY_POLICY = CompatibilityPolicy(
    minimum_version=DEFAULT_MINIMUM_BD_VERSION,
    capability_rules=(
        CapabilityRule(capability=BeadsCapability.VERSION_REPORTING),
        CapabilityRule(capability=BeadsCapability.ISSUE_JSON),
        CapabilityRule(capability=BeadsCapability.ISSUE_MUTATION),
        CapabilityRule(capability=BeadsCapability.DEPENDENCY_MUTATION),
        CapabilityRule(capability=BeadsCapability.READY_DISCOVERY),
    ),
    operations=(
        OperationContract(
            operation=SupportedOperation.INSPECT_ENVIRONMENT,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
        ),
        OperationContract(
            operation=SupportedOperation.SHOW,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_READ_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.LIST,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_READ_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.READY,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=(*_READ_CAPS, BeadsCapability.READY_DISCOVERY),
        ),
        OperationContract(
            operation=SupportedOperation.CREATE,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_WRITE_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.UPDATE,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_WRITE_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.CLOSE,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_WRITE_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.DEPENDENCY_ADD,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_DEP_CAPS,
        ),
        OperationContract(
            operation=SupportedOperation.DEPENDENCY_REMOVE,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=_DEP_CAPS,
        ),
    ),
)
