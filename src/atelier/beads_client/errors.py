"""Typed error hierarchy for the Beads client contract."""


class BeadError(RuntimeError):
    """Base error for Beads client failures."""


class BeadsCompatibilityError(BeadError):
    """Raised when the active ``bd`` surface is outside the contract."""


class UnsupportedOperationError(BeadError):
    """Raised when an operation is outside the declared client surface."""


class UnsupportedVersionError(BeadsCompatibilityError):
    """Raised when the detected ``bd`` version is unsupported."""


class CapabilityMismatchError(BeadsCompatibilityError):
    """Raised when required capabilities are unavailable."""


class BeadsCommandError(BeadError):
    """Raised when command execution fails."""


class BeadsTimeoutError(BeadsCommandError):
    """Raised when command execution exceeds the configured timeout."""


class BeadsParseError(BeadError):
    """Raised when Beads output cannot be normalized into typed models."""
