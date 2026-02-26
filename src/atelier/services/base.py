"""Base service ABC.

Services extend BaseService and implement _run(request) -> T. They raise
ServiceFailure on expected errors. __call__ catches ServiceFailure and
invokes _handle_failure; the default re-raises. Subclasses may override
_handle_failure for recovery or other handling. Callers catch ServiceFailure
for interface-specific handling (CLI dies, web returns 4xx/5xx, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from .errors import ServiceFailure

R = TypeVar("R")
T = TypeVar("T")


class BaseService(ABC, Generic[R, T]):
    """Abstract base for orchestration services.

    Subclasses implement _run(request) -> T. __call__ wraps _run, catches
    ServiceFailure, and invokes _handle_failure. Default _handle_failure
    re-raises; override for recovery or other handling.
    """

    def __call__(self, request: R) -> T:
        try:
            return self._run(request)
        except ServiceFailure as e:
            return self._handle_failure(e)

    @abstractmethod
    def _run(self, request: R) -> T:
        """Execute the service logic. Raise ServiceFailure on expected errors."""
        ...

    def _handle_failure(self, error: ServiceFailure) -> T:
        """Handle ServiceFailure. Default re-raises; override for recovery."""
        raise
