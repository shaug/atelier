from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

ServiceFailureCode = Literal[
    "validation_failed",
    "dependency_missing",
    "policy_blocked",
    "external_command_failed",
    "io_failed",
    "unexpected_state",
]

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceSuccess(Generic[T]):
    outcome: T
    success: Literal[True] = True


@dataclass(frozen=True)
class ServiceFailure:
    code: ServiceFailureCode
    message: str
    recovery_hint: str | None = None
    exception: BaseException | None = None
    success: Literal[False] = False


ServiceResult = ServiceSuccess[T] | ServiceFailure
