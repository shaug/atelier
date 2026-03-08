from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from atelier.lib.beads import (
    DEFAULT_COMPATIBILITY_POLICY,
    AsyncBeadsClient,
    Beads,
    BeadsCapability,
    BeadsCommandError,
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    BeadsParseError,
    BeadsTimeoutError,
    BeadsTransport,
    CapabilityMismatchError,
    CapabilityRule,
    CloseIssueRequest,
    CompatibilityPolicy,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    OperationContract,
    OperationOutputMode,
    ReadyIssuesRequest,
    SemanticVersion,
    ShowIssueRequest,
    SubprocessBeadsClient,
    SubprocessBeadsTransport,
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
            "issue_type": "task",
            "future_field": {"nested": True},
        }
    )

    assert record.labels == ("atelier", "changeset")
    assert record.type == "task"
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
    assert isinstance(_FakeClient(), Beads)
    assert isinstance(_FakeClient(), AsyncBeadsClient)


class _StubTransport:
    def __init__(self, responses: dict[tuple[str, ...], BeadsCommandResult]) -> None:
        self._responses = responses
        self.requests: list[BeadsCommandRequest] = []

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        self.requests.append(request)
        return self._responses[request.argv]


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int | None = 0,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.killed:
            return (self._stdout, self._stderr)
        if self._hang:
            await asyncio.sleep(60)
        return (self._stdout, self._stderr)

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9


_run = asyncio.run
_HELP_OUTPUT = "Flags:\n  -h, --help   help for command\n      --json  Output in JSON format"
_HELP_OUTPUT_NO_JSON = "Flags:\n  -h, --help   help for command"
_HELP_COMMANDS = (
    ("bd", "show", "--help"),
    ("bd", "list", "--help"),
    ("bd", "create", "--help"),
    ("bd", "update", "--help"),
    ("bd", "close", "--help"),
    ("bd", "dep", "add", "--help"),
    ("bd", "dep", "remove", "--help"),
    ("bd", "ready", "--help"),
)


def _result(
    argv: tuple[str, ...],
    *,
    stdout: str,
    returncode: int = 0,
    stderr: str = "",
) -> tuple[tuple[str, ...], BeadsCommandResult]:
    return (
        argv,
        BeadsCommandResult(
            argv=argv,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        ),
    )


def _probe_responses() -> dict[tuple[str, ...], BeadsCommandResult]:
    return {
        ("bd", "--version"): BeadsCommandResult(
            argv=("bd", "--version"),
            returncode=0,
            stdout="bd version 0.56.1 (dev)",
            stderr="",
        ),
        **{
            argv: BeadsCommandResult(argv=argv, returncode=0, stdout=_HELP_OUTPUT, stderr="")
            for argv in _HELP_COMMANDS
        },
    }


def test_subprocess_transport_raises_typed_timeout() -> None:
    process = _FakeProcess(returncode=None, hang=True)

    async def spawn(*argv: str, cwd: str | None, env: dict[str, str]) -> _FakeProcess:
        del argv, cwd, env
        return process

    transport = SubprocessBeadsTransport(spawn=spawn)

    with pytest.raises(BeadsTimeoutError, match="command timed out"):
        _run(
            transport.execute(
                BeadsCommandRequest(
                    operation=SupportedOperation.SHOW,
                    argv=("bd", "show", "at-1", "--json"),
                    timeout_seconds=0.01,
                )
            )
        )

    assert process.killed is True


def test_subprocess_client_decodes_core_json_commands() -> None:
    responses = _probe_responses()
    responses.update(
        dict(
            [
                _result(
                    ("bd", "show", "at-1", "--json"),
                    stdout='[{"id":"at-1","title":"Alpha","issue_type":"task"}]',
                ),
                _result(
                    ("bd", "list", "--json", "--status", "open", "--label", "atelier"),
                    stdout='[{"id":"at-1","issue_type":"task"}]',
                ),
                _result(
                    ("bd", "ready", "--json", "--parent", "at-epic"),
                    stdout='[{"id":"at-2","issue_type":"task"}]',
                ),
                _result(
                    (
                        "bd",
                        "create",
                        "--title",
                        "New issue",
                        "--type",
                        "task",
                        "--json",
                        "--description",
                        "desc",
                        "--labels",
                        "one,two",
                    ),
                    stdout='{"id":"at-3","issue_type":"task"}',
                ),
                _result(
                    (
                        "bd",
                        "update",
                        "at-3",
                        "--json",
                        "--status",
                        "in_progress",
                        "--set-labels",
                        "one",
                    ),
                    stdout='[{"id":"at-3","status":"in_progress","issue_type":"task"}]',
                ),
                _result(
                    ("bd", "close", "at-3", "--json", "--reason", "done"),
                    stdout='[{"id":"at-3","status":"closed","issue_type":"task"}]',
                ),
                _result(
                    ("bd", "dep", "add", "at-2", "at-1", "--json"),
                    stdout='{"issue_id":"at-2","depends_on_id":"at-1","status":"added","type":"blocks"}',
                ),
                _result(
                    ("bd", "dep", "remove", "at-2", "at-1", "--json"),
                    stdout='{"issue_id":"at-2","depends_on_id":"at-1","status":"removed"}',
                ),
                _result(
                    ("bd", "show", "at-2", "--json"),
                    stdout='[{"id":"at-2","issue_type":"task","dependencies":["at-1"]}]',
                ),
            ]
        ),
    )
    transport = _StubTransport(responses)
    client = SubprocessBeadsClient(transport=transport, env={"BEADS_DIR": "/repo/.beads"})

    shown = _run(client.show(ShowIssueRequest(issue_id="at-1")))
    listed = _run(client.list(ListIssuesRequest(status="open", labels=("atelier",))))
    ready = _run(client.ready(ReadyIssuesRequest(parent_id="at-epic")))
    created = _run(
        client.create(
            CreateIssueRequest(
                title="New issue",
                type="task",
                description="desc",
                labels=("one", "two"),
            )
        )
    )
    updated = _run(
        client.update(
            UpdateIssueRequest(
                issue_id="at-3",
                status="in_progress",
                labels=("one",),
            )
        )
    )
    closed = _run(client.close(CloseIssueRequest(issue_id="at-3", reason="done")))
    added = _run(
        client.add_dependency(DependencyMutationRequest(issue_id="at-2", dependency_id="at-1"))
    )
    _run(client.remove_dependency(DependencyMutationRequest(issue_id="at-2", dependency_id="at-1")))

    assert (shown.id, listed[0].id, ready[0].id) == ("at-1", "at-1", "at-2")
    assert (created.id, updated.status, closed.status) == ("at-3", "in_progress", "closed")
    assert added.dependencies[0].id == "at-1"


@pytest.mark.parametrize(
    ("argv", "stdout", "returncode", "stderr", "match", "client_request", "error_type"),
    [
        (
            ("bd", "show", "at-1", "--json"),
            "",
            2,
            "no issue found",
            "no issue found",
            ShowIssueRequest(issue_id="at-1"),
            BeadsCommandError,
        ),
        (
            ("bd", "show", "at-1", "--json"),
            "{not-json",
            0,
            "",
            "failed to parse JSON output",
            ShowIssueRequest(issue_id="at-1"),
            BeadsParseError,
        ),
        (
            ("bd", "ready", "--help"),
            "",
            2,
            "unknown command",
            "ready-discovery",
            ReadyIssuesRequest(),
            CapabilityMismatchError,
        ),
    ],
)
def test_subprocess_client_parse_and_capability_failures(
    argv: tuple[str, ...],
    stdout: str,
    returncode: int,
    stderr: str,
    match: str,
    client_request: ShowIssueRequest | ReadyIssuesRequest,
    error_type: type[Exception],
) -> None:
    responses = _probe_responses()
    responses.update([_result(argv, stdout=stdout, returncode=returncode, stderr=stderr)])
    client = SubprocessBeadsClient(transport=_StubTransport(responses))

    with pytest.raises(error_type, match=match):
        if isinstance(client_request, ShowIssueRequest):
            _run(client.show(client_request))
        else:
            _run(client.ready(client_request))


def test_inspect_environment_fails_closed_when_json_flag_is_missing() -> None:
    responses = _probe_responses()
    responses[("bd", "show", "--help")] = BeadsCommandResult(
        argv=("bd", "show", "--help"),
        returncode=0,
        stdout=_HELP_OUTPUT_NO_JSON,
        stderr="",
    )
    transport = _StubTransport(responses)
    client = SubprocessBeadsClient(transport=transport)

    with pytest.raises(CapabilityMismatchError, match="show: issue-json"):
        _run(client.inspect_environment())

    assert ("bd", "show", "at-1", "--json") not in [request.argv for request in transport.requests]
