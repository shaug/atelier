"""Compatibility policy for supported ``bd`` versions and capabilities."""

from __future__ import annotations

from .errors import CapabilityMismatchError, UnsupportedOperationError, UnsupportedVersionError
from .models import (
    BeadsBoundaryModel,
    BeadsCapability,
    BeadsEnvironment,
    OperationOutputMode,
    SemanticVersion,
    SupportedOperation,
)


class CapabilityRule(BeadsBoundaryModel):
    """Version window rule for a required CLI capability."""

    capability: BeadsCapability
    minimum_version: SemanticVersion | None = None
    maximum_version_exclusive: SemanticVersion | None = None
    notes: str | None = None

    def supports(self, version: SemanticVersion) -> bool:
        """Return whether the rule allows the given version."""

        if self.minimum_version and version < self.minimum_version:
            return False
        if self.maximum_version_exclusive and version >= self.maximum_version_exclusive:
            return False
        return True


class OperationContract(BeadsBoundaryModel):
    """Compatibility contract for a single supported operation."""

    operation: SupportedOperation
    output_mode: OperationOutputMode
    required_capabilities: tuple[BeadsCapability, ...] = ()


class CompatibilityPolicy(BeadsBoundaryModel):
    """Bounded compatibility policy for the Beads client contract."""

    minimum_version: SemanticVersion
    maximum_version_exclusive: SemanticVersion | None = None
    capability_rules: tuple[CapabilityRule, ...] = ()
    operations: tuple[OperationContract, ...] = ()

    def operation_contract(self, operation: SupportedOperation) -> OperationContract:
        """Return the contract for a supported operation.

        Args:
            operation: Operation to inspect.

        Returns:
            The matching operation contract.

        Raises:
            UnsupportedOperationError: If the operation is outside the
                declared client surface.
        """

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
        """Validate that a ``bd`` environment satisfies this policy.

        Args:
            environment: Installed ``bd`` environment snapshot.
            operation: Optional operation-specific compatibility check.

        Raises:
            UnsupportedVersionError: If the version is outside the global
                supported range.
            CapabilityMismatchError: If required capabilities are missing or
                version-gated out for the requested operation.
        """

        version = environment.version
        if version < self.minimum_version:
            raise UnsupportedVersionError(
                f"unsupported bd version {version}; requires >= {self.minimum_version}",
                detected_version=version,
                minimum_version=self.minimum_version,
                maximum_version_exclusive=self.maximum_version_exclusive,
            )
        if self.maximum_version_exclusive and version >= self.maximum_version_exclusive:
            raise UnsupportedVersionError(
                f"unsupported bd version {version}; requires < {self.maximum_version_exclusive}",
                detected_version=version,
                minimum_version=self.minimum_version,
                maximum_version_exclusive=self.maximum_version_exclusive,
            )

        if operation is None:
            return

        contract = self.operation_contract(operation)
        available = set(environment.capabilities)
        missing = tuple(
            capability
            for capability in contract.required_capabilities
            if capability not in available
        )
        if missing:
            names = ", ".join(capability.value for capability in missing)
            raise CapabilityMismatchError(
                f"bd is missing required capabilities for {operation.value}: {names}",
                missing_capabilities=missing,
            )

        unsupported: list[BeadsCapability] = []
        rules = {rule.capability: rule for rule in self.capability_rules}
        for capability in contract.required_capabilities:
            rule = rules.get(capability)
            if rule and not rule.supports(version):
                unsupported.append(capability)
        if unsupported:
            names = ", ".join(capability.value for capability in unsupported)
            raise CapabilityMismatchError(
                f"bd {version} is outside the supported capability window for "
                f"{operation.value}: {names}",
                unsupported_capabilities=tuple(unsupported),
            )


DEFAULT_MINIMUM_BD_VERSION = SemanticVersion(major=0, minor=56, patch=1)

DEFAULT_COMPATIBILITY_POLICY = CompatibilityPolicy(
    minimum_version=DEFAULT_MINIMUM_BD_VERSION,
    capability_rules=(
        CapabilityRule(capability=BeadsCapability.VERSION_REPORTING),
        CapabilityRule(
            capability=BeadsCapability.ISSUE_JSON,
            minimum_version=DEFAULT_MINIMUM_BD_VERSION,
            notes="Read-oriented commands prefer JSON-backed decoding.",
        ),
        CapabilityRule(
            capability=BeadsCapability.ISSUE_MUTATION,
            minimum_version=DEFAULT_MINIMUM_BD_VERSION,
        ),
        CapabilityRule(
            capability=BeadsCapability.DEPENDENCY_MUTATION,
            minimum_version=DEFAULT_MINIMUM_BD_VERSION,
        ),
        CapabilityRule(
            capability=BeadsCapability.READY_DISCOVERY,
            minimum_version=DEFAULT_MINIMUM_BD_VERSION,
        ),
    ),
    operations=(
        OperationContract(
            operation=SupportedOperation.SHOW,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_JSON,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.LIST,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_JSON,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.READY,
            output_mode=OperationOutputMode.JSON_REQUIRED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_JSON,
                BeadsCapability.READY_DISCOVERY,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.CREATE,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_MUTATION,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.UPDATE,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_MUTATION,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.CLOSE,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.ISSUE_MUTATION,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.DEPENDENCY_ADD,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.DEPENDENCY_MUTATION,
            ),
        ),
        OperationContract(
            operation=SupportedOperation.DEPENDENCY_REMOVE,
            output_mode=OperationOutputMode.TEXT_NORMALIZED,
            required_capabilities=(
                BeadsCapability.VERSION_REPORTING,
                BeadsCapability.DEPENDENCY_MUTATION,
            ),
        ),
    ),
)
