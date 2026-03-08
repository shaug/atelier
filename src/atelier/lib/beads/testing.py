"""Reusable Beads transport doubles for low-level tests."""

from __future__ import annotations

from collections.abc import Mapping

from .client import BeadsTransport
from .models import BeadsCommandRequest, BeadsCommandResult

_TransportOutcome = BeadsCommandResult | Exception


def _coerce_outcomes(
    outcome: _TransportOutcome | tuple[_TransportOutcome, ...] | list[_TransportOutcome],
) -> list[_TransportOutcome]:
    if isinstance(outcome, tuple):
        return list(outcome)
    if isinstance(outcome, list):
        return list(outcome)
    return [outcome]


class RecordingBeadsTransport(BeadsTransport):
    """Record requests and return one canned result for each execution.

    Args:
        result: Result to replay. When omitted, returns a zero-exit empty
            payload with the requested argv.
    """

    def __init__(self, result: BeadsCommandResult | None = None) -> None:
        self._result = result
        self.requests: list[BeadsCommandRequest] = []

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        self.requests.append(request)
        if self._result is None:
            return BeadsCommandResult(argv=request.argv, returncode=0)
        return self._result.model_copy(update={"argv": request.argv})


class ScriptedBeadsTransport(BeadsTransport):
    """Replay scripted transport outcomes keyed by argv and record requests.

    Args:
        responses: Mapping of argv tuples to one or more scripted outcomes.

    Raises:
        AssertionError: Raised when a request is not present in the script.
    """

    def __init__(
        self,
        responses: Mapping[
            tuple[str, ...],
            _TransportOutcome | tuple[_TransportOutcome, ...] | list[_TransportOutcome],
        ],
    ) -> None:
        self._responses = {argv: _coerce_outcomes(outcome) for argv, outcome in responses.items()}
        self.requests: list[BeadsCommandRequest] = []

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        self.requests.append(request)
        outcomes = self._responses.get(request.argv)
        if not outcomes:
            joined = " ".join(request.argv)
            raise AssertionError(f"unexpected Beads transport request: {joined}")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
