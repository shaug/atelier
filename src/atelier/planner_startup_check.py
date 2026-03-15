"""Deterministic planner-startup planning and store-backed read helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import beads, lifecycle, messages
from .lib.beads import Beads, SubprocessBeadsClient
from .store import (
    ChangesetQuery,
    EpicQuery,
    MessageQuery,
    StartupMessageRecord,
    build_atelier_store,
)

_SUPPORTED_LIST_FLAGS = frozenset({"--label", "--assignee", "--all", "--limit", "--parent"})
_LIST_FLAGS_REQUIRING_VALUE = frozenset({"--label", "--assignee", "--limit", "--parent"})
_FORBIDDEN_INVOCATION_PREFIXES = ("--db", "--db=", "--beads-dir", "--beads-dir=")


@dataclass(frozen=True)
class StartupCommandStep:
    """Metadata for one fixed planner-startup command step.

    Attributes:
        name: Stable command identity used by the startup executor.
        inputs: Explicit input names consumed by the command.
        output: Explicit output field produced by the command.
    """

    name: str
    inputs: tuple[str, ...]
    output: str


@dataclass(frozen=True)
class StartupCommandResult:
    """Structured outputs from the canonical startup command plan."""

    inbox_messages: list[dict[str, object]]
    queued_messages: list[dict[str, object]]
    epics: list[dict[str, object]]
    parity_report: object


@dataclass(frozen=True)
class StartupMessageSummary:
    """Structured inbox message summary for startup triage rendering."""

    issue_id: str
    title: str


@dataclass(frozen=True)
class StartupQueuedMessageSummary:
    """Structured queued-message summary for startup triage rendering."""

    issue_id: str
    queue: str
    title: str
    claimed_by: str | None


@dataclass(frozen=True)
class StartupIdentityViolationSummary:
    """Structured identity guardrail violation metadata."""

    issue_id: str
    status: str
    issue_type: str
    labels: tuple[str, ...]
    remediation_command: str


@dataclass(frozen=True)
class StartupIssueSummary:
    """Structured issue summary used in deferred and parity sections."""

    issue_id: str
    status: str
    title: str


@dataclass(frozen=True)
class StartupCollectionFailure:
    """Structured startup collection failure used by deterministic fallback."""

    phase: str
    error_type: str
    detail: str


@dataclass(frozen=True)
class StartupRuntimePreflight:
    """Structured runtime preflight result for planner skill checks."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class StartupDeferredChangesetGroup:
    """Deferred changesets grouped under one active epic."""

    epic: StartupIssueSummary
    changesets: tuple[StartupIssueSummary, ...]


@dataclass(frozen=True)
class StartupTriageDiagnostics:
    """Structured startup diagnostics for deterministic rendering."""

    beads_root: str
    total_epics: int
    active_top_level_work_count: int
    indexed_active_epic_count: int
    in_parity: bool
    identity_violations: tuple[StartupIdentityViolationSummary, ...]
    missing_from_index: tuple[str, ...]
    deferred_scan_limit: int
    deferred_scan_skipped_epics: int
    runtime_preflight: tuple[StartupRuntimePreflight, ...] = ()
    startup_failures: tuple[StartupCollectionFailure, ...] = ()


@dataclass(frozen=True)
class StartupTriageModel:
    """Typed startup triage model consumed by the markdown renderer."""

    inbox_messages: tuple[StartupMessageSummary, ...]
    queued_messages: tuple[StartupQueuedMessageSummary, ...]
    deferred_changesets: tuple[StartupDeferredChangesetGroup, ...]
    diagnostics: StartupTriageDiagnostics
    epic_list_markdown: str


def _build_store(*, beads_root: Path, cwd: Path, beads_client: Beads | None = None):
    client = beads_client or _build_beads_client(beads_root=beads_root, cwd=cwd)
    return build_atelier_store(beads=client)


def _build_beads_client(*, beads_root: Path, cwd: Path) -> Beads:
    return SubprocessBeadsClient(
        cwd=cwd,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )


def _epic_issue_payload(epic) -> dict[str, object]:
    return {
        "id": epic.id,
        "title": epic.title,
        "status": epic.lifecycle.value,
        "labels": list(epic.labels),
        "assignee": epic.assignee,
        "description": (
            f"workspace.root_branch: {epic.root_branch}"
            if isinstance(getattr(epic, "root_branch", None), str)
            else None
        ),
        "dependencies": [
            {
                "id": dependency.depends_on_id,
                "status": dependency.status.value if dependency.status is not None else None,
            }
            for dependency in epic.dependencies
        ],
    }


def _changeset_issue_payload(changeset) -> dict[str, object]:
    return {
        "id": changeset.id,
        "title": changeset.title,
        "status": changeset.lifecycle.value,
    }


def _render_message_summary(record) -> str:
    title = str(record.title or "").strip() or "(untitled)"
    detail_parts: list[str] = []
    if record.thread_id:
        target = record.thread_kind.value if record.thread_kind is not None else "work"
        detail_parts.append(f"{target}={record.thread_id}")
    if record.kind:
        detail_parts.append(f"kind={record.kind}")
    if record.audience:
        detail_parts.append(f"audience={','.join(record.audience)}")
    detail = f" ({'; '.join(detail_parts)})" if detail_parts else ""
    if record.body:
        return f"{title}{detail}\n{record.body}"
    return f"{title}{detail}"


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _issue_status(issue: dict[str, object]) -> str:
    canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if canonical_status:
        return canonical_status
    raw_status = str(issue.get("status") or "").strip()
    return raw_status or "unknown"


def _issue_title(issue: dict[str, object]) -> str:
    title = str(issue.get("title") or "").strip()
    return title or "(untitled)"


def _issue_id(issue: dict[str, object]) -> str:
    issue_id = str(issue.get("id") or "").strip()
    return issue_id or "(unknown)"


def build_startup_triage_model(
    *,
    beads_root: Path,
    command_result: StartupCommandResult,
    deferred_groups: list[tuple[dict[str, object], list[dict[str, object]]]],
    deferred_scan_limit: int,
    deferred_scan_skipped_epics: int,
    runtime_preflight: tuple[StartupRuntimePreflight, ...] = (),
    epic_list_markdown: str,
) -> StartupTriageModel:
    """Build a typed startup triage model from collected command outputs.

    Args:
        beads_root: Beads root path used by startup triage.
        command_result: Canonical startup command outputs.
        deferred_groups: Deferred changesets grouped by active epic.
        deferred_scan_limit: Active epic scan limit used for deferred discovery.
        deferred_scan_skipped_epics: Number of active epics skipped due to the
            configured deferred scan limit.
        epic_list_markdown: Stable `epic-list` section text.

    Returns:
        Structured startup triage model consumed by deterministic rendering.
    """

    inbox_messages = tuple(
        StartupMessageSummary(
            issue_id=_issue_id(issue),
            title=_issue_title(issue),
        )
        for issue in sorted(command_result.inbox_messages, key=_issue_sort_key)
    )
    queued_messages = tuple(
        StartupQueuedMessageSummary(
            issue_id=_issue_id(issue),
            queue=str(issue.get("queue") or "").strip() or "queue",
            title=_issue_title(issue),
            claimed_by=(
                claimed_by.strip()
                if isinstance(claimed_by := issue.get("claimed_by"), str) and claimed_by.strip()
                else None
            ),
        )
        for issue in sorted(command_result.queued_messages, key=_issue_sort_key)
    )

    normalized_groups: list[StartupDeferredChangesetGroup] = []
    for epic, changesets in sorted(deferred_groups, key=lambda group: _issue_sort_key(group[0])):
        normalized_groups.append(
            StartupDeferredChangesetGroup(
                epic=StartupIssueSummary(
                    issue_id=_issue_id(epic),
                    status=_issue_status(epic),
                    title=_issue_title(epic),
                ),
                changesets=tuple(
                    StartupIssueSummary(
                        issue_id=_issue_id(issue),
                        status=_issue_status(issue),
                        title=_issue_title(issue),
                    )
                    for issue in sorted(changesets, key=_issue_sort_key)
                ),
            )
        )
    deferred_changesets = tuple(normalized_groups)

    parity = command_result.parity_report
    sorted_identity_violations = sorted(
        tuple(getattr(parity, "missing_executable_identity", ())),
        key=lambda item: str(getattr(item, "issue_id", "") or "").strip(),
    )
    identity_violations = tuple(
        StartupIdentityViolationSummary(
            issue_id=str(getattr(item, "issue_id", "") or "").strip() or "(unknown)",
            status=str(getattr(item, "status", "") or "").strip() or "missing",
            issue_type=str(getattr(item, "issue_type", "") or "").strip() or "missing",
            labels=tuple(
                sorted(
                    str(label).strip()
                    for label in tuple(getattr(item, "labels", ()))
                    if str(label).strip()
                )
            ),
            remediation_command=(
                str(getattr(item, "remediation_command", "") or "").strip()
                or "(missing remediation command)"
            ),
        )
        for item in sorted_identity_violations
    )

    missing_from_index = tuple(
        sorted(
            str(issue_id).strip()
            for issue_id in tuple(getattr(parity, "missing_from_index", ()))
            if str(issue_id).strip()
        )
    )
    diagnostics = StartupTriageDiagnostics(
        beads_root=str(beads_root),
        total_epics=len(command_result.epics),
        active_top_level_work_count=int(getattr(parity, "active_top_level_work_count", 0)),
        indexed_active_epic_count=int(getattr(parity, "indexed_active_epic_count", 0)),
        in_parity=bool(getattr(parity, "in_parity", False)),
        identity_violations=identity_violations,
        missing_from_index=missing_from_index,
        deferred_scan_limit=max(0, int(deferred_scan_limit)),
        deferred_scan_skipped_epics=max(0, int(deferred_scan_skipped_epics)),
        runtime_preflight=tuple(runtime_preflight),
    )
    return StartupTriageModel(
        inbox_messages=inbox_messages,
        queued_messages=queued_messages,
        deferred_changesets=deferred_changesets,
        diagnostics=diagnostics,
        epic_list_markdown=epic_list_markdown,
    )


def _normalize_startup_error_detail(error: BaseException) -> str:
    raw_detail = str(error).strip()
    if not raw_detail:
        raw_detail = "startup collection failed without additional detail"
    first_line = raw_detail.splitlines()[0].strip()
    collapsed = " ".join(first_line.split())
    return collapsed or "startup collection failed without additional detail"


def _fallback_epic_list_markdown(epic_list_markdown: str | None) -> str:
    normalized = str(epic_list_markdown or "").strip()
    if normalized:
        return normalized
    return "Epics by state:\n- unavailable (startup triage failed before epic rendering)"


def build_startup_triage_failure_model(
    *,
    beads_root: Path,
    phase: str,
    error: BaseException,
    runtime_preflight: tuple[StartupRuntimePreflight, ...] = (),
    epic_list_markdown: str | None = None,
) -> StartupTriageModel:
    """Build a deterministic startup triage model for fallback/error paths.

    Args:
        beads_root: Beads root path used by startup triage.
        phase: Stable failure phase identifier.
        error: Original startup collection/rendering error.
        epic_list_markdown: Optional pre-rendered epic-list section.

    Returns:
        Startup triage model that preserves a deterministic output shape while
        reporting structured failure details.
    """

    failure = StartupCollectionFailure(
        phase=str(phase).strip() or "startup_collection",
        error_type=(type(error).__name__ or "Exception"),
        detail=_normalize_startup_error_detail(error),
    )
    diagnostics = StartupTriageDiagnostics(
        beads_root=str(beads_root),
        total_epics=0,
        active_top_level_work_count=0,
        indexed_active_epic_count=0,
        in_parity=False,
        identity_violations=(),
        missing_from_index=(),
        deferred_scan_limit=0,
        deferred_scan_skipped_epics=0,
        runtime_preflight=tuple(runtime_preflight),
        startup_failures=(failure,),
    )
    return StartupTriageModel(
        inbox_messages=(),
        queued_messages=(),
        deferred_changesets=(),
        diagnostics=diagnostics,
        epic_list_markdown=_fallback_epic_list_markdown(epic_list_markdown),
    )


def render_startup_triage_markdown(model: StartupTriageModel) -> str:
    """Render deterministic startup markdown from a typed triage model.

    Args:
        model: Startup triage model.

    Returns:
        Stable markdown output for planner startup triage.
    """

    lines: list[str] = [
        "Planner startup overview",
        f"- Beads root: {model.diagnostics.beads_root}",
    ]
    diagnostics = model.diagnostics

    if diagnostics.startup_failures:
        lines.append("Startup collection fallback (deterministic):")
        for failure in diagnostics.startup_failures:
            lines.append(
                f"- phase={failure.phase} error={failure.error_type} detail={failure.detail}"
            )

    if diagnostics.runtime_preflight:
        lines.append("Planner skill runtime preflight:")
        for result in diagnostics.runtime_preflight:
            lines.append(f"- {result.name}: {result.status} ({result.detail})")

    if model.inbox_messages:
        lines.append("Unread messages:")
        for message in model.inbox_messages:
            lines.append(f"- {message.issue_id} {message.title}")
    else:
        lines.append("No unread messages.")

    if model.queued_messages:
        lines.append("Queued messages:")
        for queued_message in model.queued_messages:
            claim_state = (
                f"claimed by {queued_message.claimed_by}"
                if queued_message.claimed_by
                else "unclaimed"
            )
            lines.append(
                f"- {queued_message.issue_id} [{queued_message.queue}] {queued_message.title} "
                f"| claim: {claim_state}"
            )
    else:
        lines.append("No queued messages.")

    lines.append(f"- Total epics: {diagnostics.total_epics}")
    lines.append(
        "- Active top-level work (open/in_progress/blocked): "
        f"{diagnostics.active_top_level_work_count}"
    )
    lines.append(
        f"- Indexed active epics (at:epic discovery): {diagnostics.indexed_active_epic_count}"
    )
    if diagnostics.in_parity:
        lines.append("Epic discovery parity: ok")
    if diagnostics.identity_violations:
        lines.append("Identity guardrail violations (deterministic remediation):")
        for violation in diagnostics.identity_violations:
            labels = ", ".join(violation.labels) if violation.labels else "(none)"
            lines.append(
                f"- {violation.issue_id} [status={violation.status} "
                f"type={violation.issue_type}] labels={labels}"
            )
            lines.append(f"  remediation: {violation.remediation_command}")
    if diagnostics.missing_from_index:
        lines.append("Discovery index mismatch for executable top-level work:")
        for issue_id in diagnostics.missing_from_index:
            lines.append(f"- {issue_id}")
        lines.append(
            "  remediation: run `bd prime`; if mismatch persists, run "
            "`bd doctor --fix --yes` and rerun startup."
        )

    if model.deferred_changesets:
        lines.append("Deferred changesets under open/in-progress/blocked epics:")
        for group in model.deferred_changesets:
            lines.append(f"- {group.epic.issue_id} [{group.epic.status}] {group.epic.title}")
            for issue in group.changesets:
                lines.append(f"  - {issue.issue_id} [{issue.status}] {issue.title}")
    else:
        lines.append("No deferred changesets under open/in-progress/blocked epics.")

    if diagnostics.deferred_scan_skipped_epics:
        lines.append(
            "Deferred changeset scan limited to first "
            f"{diagnostics.deferred_scan_limit} active epics; skipped "
            f"{diagnostics.deferred_scan_skipped_epics}."
        )

    lines.extend(model.epic_list_markdown.splitlines())
    return "\n".join(lines)


_STARTUP_COMMAND_PLAN: tuple[StartupCommandStep, ...] = (
    StartupCommandStep(
        name="list_inbox_unread_messages",
        inputs=("agent_id",),
        output="inbox_messages",
    ),
    StartupCommandStep(
        name="list_queue_unread_messages",
        inputs=(),
        output="queued_messages",
    ),
    StartupCommandStep(
        name="list_indexed_epics",
        inputs=(),
        output="epics",
    ),
    StartupCommandStep(
        name="compute_epic_discovery_parity",
        inputs=("epics",),
        output="parity_report",
    ),
)


def startup_command_plan() -> tuple[StartupCommandStep, ...]:
    """Return the canonical planner-startup command plan in execution order.

    Returns:
        Ordered startup command steps with explicit input and output contracts.
    """

    return _STARTUP_COMMAND_PLAN


def validate_startup_list_invocation(args: list[str]) -> None:
    """Validate a startup helper `bd list` invocation.

    Args:
        args: `bd` arguments without the leading binary name.

    Raises:
        ValueError: If the invocation uses unsupported syntax or forbidden
            flags.
    """

    if not args:
        raise ValueError("startup helper requires a non-empty bd invocation")
    if args[0] != "list":
        raise ValueError("startup helper supports only `bd list` invocations")

    index = 1
    while index < len(args):
        token = str(args[index]).strip()
        lower = token.lower()
        if any(
            lower == blocked or lower.startswith(blocked)
            for blocked in _FORBIDDEN_INVOCATION_PREFIXES
        ):
            raise ValueError(f"forbidden startup bd invocation flag: {token}")
        if lower == "--json":
            raise ValueError("startup helper manages JSON mode; do not pass --json")
        if token.startswith("--"):
            if token not in _SUPPORTED_LIST_FLAGS:
                raise ValueError(f"unsupported startup bd list flag: {token}")
            if token in _LIST_FLAGS_REQUIRING_VALUE:
                if index + 1 >= len(args):
                    raise ValueError(f"startup bd list flag requires a value: {token}")
                value = str(args[index + 1]).strip()
                if not value or value.startswith("--"):
                    raise ValueError(f"startup bd list flag requires a value: {token}")
                index += 2
                continue
        index += 1


@dataclass(frozen=True)
class StartupBeadsInvocationHelper:
    """Shared store-backed helper for planner-startup command execution."""

    beads_root: Path
    cwd: Path

    def _store(self):
        cached = getattr(self, "_store_cache", None)
        if cached is None:
            cached = _build_store(beads_root=self.beads_root, cwd=self.cwd)
            object.__setattr__(self, "_store_cache", cached)
        return cached

    def list_inbox_messages(
        self,
        agent_id: str,
        *,
        unread_only: bool = True,
    ) -> list[dict[str, object]]:
        """List planner inbox messages via store-native message projections."""

        issues = self._list_startup_messages(unread_only=unread_only)
        matches: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for issue in issues:
            issue_id = issue.id
            if getattr(issue, "queue", None):
                continue
            routed_attention = any(
                role in ("planner", "operator")
                for role in (
                    *tuple(getattr(issue, "blocking_roles", ())),
                    *tuple(getattr(issue, "audience", ())),
                )
            )
            if not routed_attention:
                continue
            title = _render_message_summary(issue).replace("\n", " | ")
            if issue_id in seen_ids:
                continue
            seen_ids.add(issue_id)
            matches.append({"id": issue.id, "title": title})
        return matches

    def list_queue_messages(
        self,
        *,
        queue: str | None = None,
        unclaimed_only: bool = True,
        unread_only: bool = True,
    ) -> list[dict[str, object]]:
        """List queued message beads from store-backed message queries."""

        issues = self._list_startup_messages(queue=queue, unread_only=unread_only)
        matches: list[dict[str, object]] = []
        for issue in issues:
            normalized_claim = issue.claimed_by
            if unclaimed_only and issue.claimed_by:
                continue
            matches.append(
                {
                    "id": issue.id,
                    "title": issue.title,
                    "queue": issue.queue or "queue",
                    "claimed_by": normalized_claim,
                }
            )
        return matches

    def _list_startup_messages(
        self,
        *,
        queue: str | None = None,
        unread_only: bool,
    ) -> tuple[StartupMessageRecord, ...]:
        store = self._store()
        query = MessageQuery(queue=queue, unread_only=unread_only)
        return asyncio.run(store.list_startup_messages(query))

    def list_epics(self, *, include_closed: bool = False) -> list[dict[str, object]]:
        """List indexed epics through the Atelier store."""

        epics = asyncio.run(self._store().list_epics(EpicQuery(include_closed=include_closed)))
        return [_epic_issue_payload(epic) for epic in epics]

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool = False,
    ) -> list[dict[str, object]]:
        """List descendant changesets (leaf work beads under a parent)."""

        changesets = asyncio.run(
            self._store().list_changesets(
                ChangesetQuery(epic_id=parent_id, include_closed=include_closed)
            )
        )
        return [_changeset_issue_payload(changeset) for changeset in changesets]

    def epic_discovery_parity_report(self) -> object:
        """Return startup epic discovery parity diagnostics."""

        return asyncio.run(self._store().epic_discovery_parity())


def execute_startup_command_plan(
    agent_id: str,
    *,
    helper: StartupBeadsInvocationHelper,
) -> StartupCommandResult:
    """Execute the canonical startup command plan in fixed order.

    Args:
        agent_id: Planner agent id used for inbox lookup.
        helper: Shared Beads invocation helper bound to beads root + repo cwd.

    Returns:
        Structured startup command outputs.

    Raises:
        RuntimeError: If the plan contains an unknown step.
    """

    inbox_messages: list[dict[str, object]] = []
    queued_messages: list[dict[str, object]] = []
    epics: list[dict[str, object]] = []
    parity_report: object | None = None

    for step in startup_command_plan():
        if step.name == "list_inbox_unread_messages":
            inbox_messages = helper.list_inbox_messages(agent_id, unread_only=True)
            continue
        if step.name == "list_queue_unread_messages":
            queued_messages = helper.list_queue_messages(unclaimed_only=False, unread_only=True)
            continue
        if step.name == "list_indexed_epics":
            epics = helper.list_epics(include_closed=False)
            continue
        if step.name == "compute_epic_discovery_parity":
            parity_report = helper.epic_discovery_parity_report()
            continue
        raise RuntimeError(f"unknown startup command step: {step.name}")

    if parity_report is None:
        parity_report = helper.epic_discovery_parity_report()
    return StartupCommandResult(
        inbox_messages=inbox_messages,
        queued_messages=queued_messages,
        epics=epics,
        parity_report=parity_report,
    )
