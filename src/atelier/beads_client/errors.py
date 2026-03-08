"""Typed error taxonomy for the Beads client contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import BeadsCapability, SemanticVersion


class BeadError(RuntimeError):
    """Base error for Beads client failures."""

    def __init__(self, detail: str, *, operation: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.operation = operation

    def __str__(self) -> str:
        return self.detail


class BeadsCompatibilityError(BeadError):
    """Raised when the active ``bd`` installation is outside the contract."""


class UnsupportedOperationError(BeadError):
    """Raised when an operation is outside the declared client contract."""


class UnsupportedVersionError(BeadsCompatibilityError):
    """Raised when the detected ``bd`` version is outside support."""

    def __init__(
        self,
        detail: str,
        *,
        detected_version: SemanticVersion,
        minimum_version: SemanticVersion,
        maximum_version_exclusive: SemanticVersion | None = None,
    ) -> None:
        super().__init__(detail)
        self.detected_version = detected_version
        self.minimum_version = minimum_version
        self.maximum_version_exclusive = maximum_version_exclusive


class CapabilityMismatchError(BeadsCompatibilityError):
    """Raised when required CLI capabilities are unavailable."""

    def __init__(
        self,
        detail: str,
        *,
        missing_capabilities: tuple[BeadsCapability, ...] = (),
        unsupported_capabilities: tuple[BeadsCapability, ...] = (),
    ) -> None:
        super().__init__(detail)
        self.missing_capabilities = missing_capabilities
        self.unsupported_capabilities = unsupported_capabilities


class BeadsCommandError(BeadError):
    """Raised when command execution fails."""

    def __init__(
        self,
        detail: str,
        *,
        operation: str | None = None,
        argv: tuple[str, ...] = (),
        returncode: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(detail, operation=operation)
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class BeadsTimeoutError(BeadsCommandError):
    """Raised when command execution exceeds the configured timeout."""


class BeadsParseError(BeadError):
    """Raised when Beads output cannot be normalized into typed models."""

    def __init__(self, detail: str, *, source: str | None = None) -> None:
        super().__init__(detail)
        self.source = source
