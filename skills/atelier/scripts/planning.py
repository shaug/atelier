#!/usr/bin/env python3
"""Plan, revise, preview, and explicitly promote one Atelier assignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills.atelier.scripts.git_mailbox import (
    FileChange,
    GitMailboxWriter,
    MailboxTransitionRejected,
    MailboxWriteError,
    TransitionContext,
    TransitionPlan,
    WriteResult,
    run_git,
)
from skills.atelier.scripts.host_boundary import HostBoundaryError, validate_observation
from skills.atelier.scripts.mailbox import (
    MailboxValidationError,
    _read_yaml,
    reconstruct_mailbox,
    validate_project_policy,
)

AUTHORITY_ACTIONS = frozenset(
    {
        "repository.candidate.create",
        "repository.candidate.push",
        "pull_request.create",
        "pull_request.update",
        "review.reply",
        "review.resolve",
    }
)
EVIDENCE_NAMES = frozenset(
    {
        "candidate-remote-reachable",
        "pull-request-head-current",
        "pull-request-open",
        "pull-request-mergeable",
        "required-checks-pass",
        "required-validation-reported",
        "independent-review-current",
        "unresolved-feedback-zero",
    }
)
ID_PATTERN = re.compile(
    r"^(?P<prefix>prj|ini|wrk)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
GITHUB_ISSUE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repository>[^/]+)/issues/(?P<number>[1-9][0-9]*)$"
)
SECTION_NAMES = (
    "intent",
    "rationale",
    "scope",
    "non_goals",
    "constraints",
    "edge_cases",
    "related_context",
    "done_definition",
    "verification_expectations",
    "review_shape_guidance",
)
INITIATIVE_SECTION_NAMES = (
    "intent",
    "rationale",
    "non_goals",
    "constraints",
    "edge_cases",
    "related_context",
    "outcome",
)


class PlanningError(RuntimeError):
    """A planning transition cannot be trusted or safely applied."""


@dataclass(frozen=True)
class InitiativeDraft:
    """One optional non-authoritative cross-project planning document."""

    id: str
    title: str
    intent: str
    rationale: str
    non_goals: str
    constraints: str
    edge_cases: str
    related_context: str
    outcome: str


@dataclass(frozen=True)
class AssignmentDraft:
    """The complete worker-readable contract for one project assignment."""

    id: str
    title: str
    project_id: str
    initiative_id: str | None
    dependencies: tuple[str, ...]
    replaces: tuple[str, ...]
    ticket_number: int
    ticket_url: str
    intent: str
    rationale: str
    scope: str
    non_goals: str
    constraints: str
    edge_cases: str
    related_context: str
    done_definition: str
    verification_expectations: str
    review_shape_guidance: str


@dataclass(frozen=True)
class PolicyTarget:
    """A live project-policy read boundary."""

    checkout: Path
    remote: str
    canonical_ref: str
    path: str


@dataclass(frozen=True)
class ApprovalEnvelope:
    """The exact durable authority and acceptance proposal shown to the operator."""

    authority_ceiling: tuple[str, ...]
    required_evidence: tuple[str, ...]


@dataclass(frozen=True)
class PlanPreview:
    """An exact preview token and the identities from which it was derived."""

    schema: str
    work_id: str
    revision: int
    rendered_assignment: str
    rendered_initiative: str | None
    work_digest: str
    initiative_digest: str | None
    ticket_observation_digest: str
    ticket_repository: str
    ticket_number: int
    ticket_url: str
    policy_repository: str
    policy_commit: str
    policy_path: str
    authority_ceiling: tuple[str, ...]
    required_evidence: tuple[str, ...]
    preview_digest: str


@dataclass(frozen=True)
class PlanningResult:
    """One verified canonical mailbox write."""

    operation: str
    work_id: str
    revision: int
    status: str
    commit: str
    base_revision: str
    branch: str
    attempts: int
    recovered: bool


@dataclass(frozen=True)
class _CurrentPolicy:
    value: dict[str, Any]
    repository: str
    commit: str
    path: str


def new_identifier(prefix: str) -> str:
    """Generate one lowercase UUIDv7 identifier with the requested Atelier prefix."""

    if prefix not in {"ini", "wrk"}:
        raise PlanningError("planning identifiers support only ini and wrk prefixes")
    milliseconds = int(time.time() * 1000)
    if milliseconds >= 1 << 48:
        raise PlanningError("current time exceeds the UUIDv7 timestamp range")
    random_bits = secrets.randbits(74)
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    hexadecimal = f"{value:032x}"
    uuid = (
        f"{hexadecimal[:8]}-{hexadecimal[8:12]}-{hexadecimal[12:16]}-"
        f"{hexadecimal[16:20]}-{hexadecimal[20:]}"
    )
    return f"{prefix}_{uuid}"


class Planner:
    """Production plan-mode transitions over one canonical Git mailbox."""

    def __init__(
        self,
        remote: str,
        branch: str,
        *,
        max_attempts: int = 3,
        writer: GitMailboxWriter | None = None,
    ):
        if not remote or remote.startswith("-"):
            raise PlanningError("mailbox remote must be nonempty and must not begin with '-'")
        self.remote = remote
        self.branch = branch
        self.writer = writer or GitMailboxWriter(
            remote,
            branch,
            max_attempts=max_attempts,
        )

    def create_draft(
        self,
        assignment: AssignmentDraft,
        *,
        observation_path: Path,
        observation_not_before: datetime,
        initiative: InitiativeDraft | None = None,
        now: datetime | None = None,
    ) -> PlanningResult:
        """Create one non-executable assignment and optional initiative."""

        _validate_assignment_input(assignment)
        _validate_initiative_input(initiative, assignment.initiative_id)
        observation = _validated_observation(
            observation_path,
            not_before=observation_not_before,
            now=now,
        )

        def revalidate(context: TransitionContext) -> None:
            current_observation = _validated_observation(
                observation_path,
                not_before=observation_not_before,
                now=now,
            )
            _require_same_observation(observation, current_observation)
            _require_project_and_ticket(context, assignment, current_observation)
            work_path = _work_path(assignment.id)
            if (context.checkout / work_path).exists():
                raise MailboxTransitionRejected(f"{assignment.id}: work identifier already exists")
            if initiative is not None and (
                context.checkout / _initiative_path(initiative.id)
            ).exists():
                raise MailboxTransitionRejected(
                    f"{initiative.id}: initiative identifier already exists"
                )

        def plan(context: TransitionContext) -> TransitionPlan:
            changes: list[FileChange] = []
            if initiative is not None:
                changes.append(
                    FileChange(
                        _initiative_path(initiative.id),
                        _render_initiative(initiative),
                    )
                )
            changes.append(FileChange(_work_path(assignment.id), _render_work(assignment, 1)))
            return TransitionPlan(
                f"plan: create draft {assignment.id}",
                tuple(changes),
            )

        result = self.writer.publish(
            "plan.create-draft",
            revalidate=revalidate,
            plan=plan,
        )
        return _planning_result(result, assignment.id, 1, "draft")

    def revise_draft(
        self,
        assignment: AssignmentDraft,
        *,
        expected_revision: int,
        observation_path: Path,
        observation_not_before: datetime,
        initiative: InitiativeDraft | None = None,
        expected_initiative_digest: str | None = None,
        now: datetime | None = None,
    ) -> PlanningResult:
        """Replace one exact draft revision and increment its revision once."""

        _require_expected_revision(expected_revision)
        _validate_assignment_input(assignment)
        _validate_initiative_input(initiative, assignment.initiative_id)
        if initiative is None:
            if expected_initiative_digest is not None:
                raise PlanningError(
                    "expected_initiative_digest is allowed only when revising an initiative"
                )
        elif (
            not isinstance(expected_initiative_digest, str)
            or DIGEST_PATTERN.fullmatch(expected_initiative_digest) is None
        ):
            raise PlanningError(
                "revising an initiative requires its expected lowercase SHA-256 digest"
            )
        observation = _validated_observation(
            observation_path,
            not_before=observation_not_before,
            now=now,
        )

        def revalidate(context: TransitionContext) -> None:
            current_observation = _validated_observation(
                observation_path,
                not_before=observation_not_before,
                now=now,
            )
            _require_same_observation(observation, current_observation)
            _require_project_and_ticket(context, assignment, current_observation)
            current, _ = _read_document(context.checkout / _work_path(assignment.id))
            if current["status"] != "draft":
                raise MailboxTransitionRejected(
                    f"{assignment.id}: only draft work may be revised"
                )
            if current["revision"] != expected_revision:
                raise MailboxTransitionRejected(
                    f"{assignment.id}: expected revision {expected_revision}, "
                    f"found {current['revision']}"
                )
            if initiative is not None:
                _require_initiative_digest(
                    context.checkout,
                    initiative.id,
                    expected_initiative_digest,
                )

        def plan(context: TransitionContext) -> TransitionPlan:
            changes: list[FileChange] = []
            if initiative is not None:
                initiative_path = _initiative_path(initiative.id)
                _require_initiative_digest(
                    context.checkout,
                    initiative.id,
                    expected_initiative_digest,
                )
                initiative_content = _render_initiative(initiative)
                if (context.checkout / initiative_path).read_text(
                    encoding="utf-8"
                ) != initiative_content:
                    changes.append(FileChange(initiative_path, initiative_content))
            changes.append(
                FileChange(
                    _work_path(assignment.id),
                    _render_work(assignment, expected_revision + 1),
                )
            )
            return TransitionPlan(
                f"plan: revise draft {assignment.id} to revision {expected_revision + 1}",
                tuple(changes),
            )

        result = self.writer.publish(
            "plan.revise-draft",
            revalidate=revalidate,
            plan=plan,
        )
        return _planning_result(
            result,
            assignment.id,
            expected_revision + 1,
            "draft",
        )

    def preview_approval(
        self,
        work_id: str,
        *,
        expected_revision: int,
        envelope: ApprovalEnvelope,
        policy_target: PolicyTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None = None,
    ) -> PlanPreview:
        """Read live state and return the exact proposal an operator may approve."""

        _require_identifier(work_id, "wrk")
        _require_expected_revision(expected_revision)
        _validate_envelope(envelope)
        with tempfile.TemporaryDirectory(prefix="atelier-plan-preview-") as temporary:
            checkout, _ = self._read_mailbox(Path(temporary))
            return _build_preview(
                checkout,
                remote=self.remote,
                branch=self.branch,
                work_id=work_id,
                expected_revision=expected_revision,
                envelope=envelope,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )

    def approve(
        self,
        preview: PlanPreview,
        *,
        approved_by: str,
        approved_at: datetime,
        policy_target: PolicyTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None = None,
    ) -> PlanningResult:
        """Promote exactly one previewed draft after explicit operator confirmation."""

        if approved_by != "operator":
            raise PlanningError("only an explicit operator approval may promote work")
        if approved_at.utcoffset() is None:
            raise PlanningError("approval timestamp must include a UTC offset")
        if observation_not_before < approved_at:
            raise PlanningError(
                "approval requires a GitHub live-read boundary at or after "
                "the operator confirmation"
            )
        envelope = ApprovalEnvelope(
            authority_ceiling=preview.authority_ceiling,
            required_evidence=preview.required_evidence,
        )
        _validate_envelope(envelope)
        approved_at_text = _timestamp(approved_at)

        def current_preview(context: TransitionContext) -> PlanPreview:
                return _build_preview(
                    context.checkout,
                    remote=self.remote,
                branch=self.branch,
                work_id=preview.work_id,
                expected_revision=preview.revision,
                envelope=envelope,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )

        def revalidate(context: TransitionContext) -> None:
            candidate = current_preview(context)
            _require_preview_match(preview, candidate)

        def plan(context: TransitionContext) -> TransitionPlan:
            candidate = current_preview(context)
            _require_preview_match(preview, candidate)
            work, body = _read_document(context.checkout / _work_path(preview.work_id))
            work["status"] = "approved"
            work["approval"] = {
                "approved_by": "operator",
                "approved_at": approved_at_text,
                "revision": candidate.revision,
                "policy": {
                    "repository": candidate.policy_repository,
                    "commit": candidate.policy_commit,
                    "path": candidate.policy_path,
                },
                "authority_ceiling": list(candidate.authority_ceiling),
                "acceptance": {
                    "mode": "operator",
                    "required_evidence": list(candidate.required_evidence),
                },
            }
            return TransitionPlan(
                f"plan: approve {preview.work_id} revision {candidate.revision}",
                (
                    FileChange(
                        _work_path(preview.work_id),
                        _render_document(work, body),
                    ),
                ),
            )

        result = self.writer.publish(
            "plan.approve",
            revalidate=revalidate,
            plan=plan,
        )
        return _planning_result(
            result,
            preview.work_id,
            preview.revision,
            "approved",
        )

    def _read_mailbox(self, temporary: Path) -> tuple[Path, str]:
        checkout = temporary / "mailbox"
        initialized = run_git(None, ("init", str(checkout)))
        _require_git(initialized, "initialize mailbox preview checkout")
        added = run_git(checkout, ("remote", "add", "origin", self.remote))
        _require_git(added, "configure mailbox preview remote")
        fetched = run_git(
            checkout,
            (
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
            ),
        )
        _require_git(fetched, "fetch canonical mailbox branch")
        commit = _git_output(
            checkout,
            ("rev-parse", f"refs/remotes/origin/{self.branch}"),
            "resolve canonical mailbox head",
        )
        checked_out = run_git(checkout, ("checkout", "--detach", commit))
        _require_git(checked_out, "check out canonical mailbox head")
        return checkout, commit


def _build_preview(
    checkout: Path,
    *,
    remote: str,
    branch: str,
    work_id: str,
    expected_revision: int,
    envelope: ApprovalEnvelope,
    policy_target: PolicyTarget,
    observation_path: Path,
    observation_not_before: datetime,
    now: datetime | None,
) -> PlanPreview:
    mailbox = reconstruct_mailbox(checkout)
    work_path = checkout / _work_path(work_id)
    work, _ = _read_document(work_path)
    if work["status"] != "draft":
        raise PlanningError(f"{work_id}: only draft work may be previewed for approval")
    if work["revision"] != expected_revision:
        raise PlanningError(
            f"{work_id}: expected revision {expected_revision}, found {work['revision']}"
        )
    project = _read_project(checkout, work["project_id"])
    observation = _validated_observation(
        observation_path,
        not_before=observation_not_before,
        now=now,
    )
    _require_work_ticket(work, project, observation)
    policy = _read_current_policy(policy_target)
    _require_policy_matches(
        policy,
        project=project,
        work=work,
        observation=observation,
        mailbox_remote=remote,
        mailbox_branch=branch,
        mailbox_realm=mailbox["realm_id"],
        envelope=envelope,
    )
    ticket_digest = _ticket_material_digest(observation["issue"], policy.value)
    rendered_assignment = work_path.read_text(encoding="utf-8")
    work_digest = _digest_bytes(rendered_assignment.encode())
    rendered_initiative = None
    initiative_digest = None
    initiative_id = work["initiative_id"]
    if initiative_id is not None:
        initiative_path = checkout / _initiative_path(initiative_id)
        initiative, _ = _read_document(initiative_path)
        if initiative["id"] != initiative_id:
            raise PlanningError(f"{initiative_id}: initiative document identity mismatch")
        rendered_initiative = initiative_path.read_text(encoding="utf-8")
        initiative_digest = _digest_bytes(rendered_initiative.encode())
    issue = observation["issue"]
    preview = PlanPreview(
        schema="atelier.plan-preview/v1",
        work_id=work_id,
        revision=expected_revision,
        rendered_assignment=rendered_assignment,
        rendered_initiative=rendered_initiative,
        work_digest=work_digest,
        initiative_digest=initiative_digest,
        ticket_observation_digest=ticket_digest,
        ticket_repository=observation["repository"]["name_with_owner"],
        ticket_number=issue["number"],
        ticket_url=issue["url"],
        policy_repository=policy.repository,
        policy_commit=policy.commit,
        policy_path=policy.path,
        authority_ceiling=envelope.authority_ceiling,
        required_evidence=envelope.required_evidence,
        preview_digest="",
    )
    return replace(preview, preview_digest=_digest_json(_preview_token_value(preview)))


def _require_project_and_ticket(
    context: TransitionContext,
    assignment: AssignmentDraft,
    observation: Mapping[str, Any],
) -> None:
    project = _read_project(context.checkout, assignment.project_id)
    work = {
        "native_ticket": {
            "provider": "github",
            "id": str(assignment.ticket_number),
            "url": assignment.ticket_url,
        }
    }
    _require_work_ticket(work, project, observation)
    for dependency in assignment.dependencies:
        if not (context.checkout / _work_path(dependency)).is_file():
            raise MailboxTransitionRejected(
                f"{assignment.id}: dependency {dependency} does not exist"
            )
    for replaced in assignment.replaces:
        if not (context.checkout / _work_path(replaced)).is_file():
            raise MailboxTransitionRejected(
                f"{assignment.id}: replacement target {replaced} does not exist"
            )


def _require_work_ticket(
    work: Mapping[str, Any],
    project: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> None:
    if project["status"] != "active":
        raise PlanningError(f"{project['id']}: project is not active")
    repository = observation["repository"]["name_with_owner"]
    expected_repository = project["repository"].removeprefix("github:")
    if repository != expected_repository:
        raise PlanningError(
            f"{project['id']}: project repository {expected_repository} "
            f"does not match observed repository {repository}"
        )
    ticket = work["native_ticket"]
    issue = observation["issue"]
    if ticket is None:
        raise PlanningError("assignment is not linked to a native ticket")
    if ticket["provider"] != "github":
        raise PlanningError("initial plan mode supports only GitHub tickets")
    if ticket["id"] != str(issue["number"]) or ticket["url"] != issue["url"]:
        raise PlanningError("assignment native ticket does not match the live observation")
    match = GITHUB_ISSUE_URL.fullmatch(ticket["url"])
    if (
        match is None
        or f"{match.group('owner')}/{match.group('repository')}" != repository
        or int(match.group("number")) != issue["number"]
    ):
        raise PlanningError("assignment native ticket URL is not canonical for the project")


def _require_policy_matches(
    policy: _CurrentPolicy,
    *,
    project: Mapping[str, Any],
    work: Mapping[str, Any],
    observation: Mapping[str, Any],
    mailbox_remote: str,
    mailbox_branch: str,
    mailbox_realm: str,
    envelope: ApprovalEnvelope,
) -> None:
    value = policy.value
    expected_repository = project["repository"]
    if policy.repository != expected_repository:
        raise PlanningError(
            f"policy repository {policy.repository} does not match project {expected_repository}"
        )
    if project["policy"] != {
        "repository": policy.repository,
        "path": policy.path,
    }:
        raise PlanningError("project policy locator contradicts the current policy target")
    if value["repository"]["identity"] != expected_repository:
        raise PlanningError("project policy repository identity contradicts the project")
    if value["mailbox"]["remote"] != mailbox_remote:
        raise PlanningError("project policy mailbox remote does not match this planner")
    if value["mailbox"]["canonical_branch"] != mailbox_branch:
        raise PlanningError("project policy mailbox branch does not match this planner")
    if value["mailbox"]["realm_id"] != mailbox_realm:
        raise PlanningError("project policy realm does not match the canonical mailbox")
    if value["mailbox"]["project_id"] != work["project_id"]:
        raise PlanningError("project policy project identity does not match the assignment")
    if value["ticket"]["provider"] != "github":
        raise PlanningError("project policy does not permit GitHub tickets")
    issue = observation["issue"]
    if issue["state"].lower() not in value["ticket"]["allowed_states"]:
        raise PlanningError(f"ticket #{issue['number']} is not in an allowed state")
    if value["ticket"]["require_no_blockers"]:
        blockers = [item for item in issue["blocked_by"] if item["state"] != "CLOSED"]
        if blockers:
            numbers = ", ".join(f"#{item['number']}" for item in blockers)
            raise PlanningError(f"ticket #{issue['number']} has unresolved blockers: {numbers}")
    if observation["pull_request"] is not None:
        raise PlanningError(
            f"ticket #{issue['number']} already has a canonical pull-request observation"
        )
    policy_authority = set(value["authority"]["allow"])
    if not set(envelope.authority_ceiling) <= policy_authority:
        raise PlanningError("approval authority exceeds the current project policy")
    policy_evidence = set(value["acceptance"]["evidence"])
    if not policy_evidence <= set(envelope.required_evidence):
        raise PlanningError("approval omits evidence required by the current project policy")


def _read_current_policy(target: PolicyTarget) -> _CurrentPolicy:
    if not target.checkout.is_dir():
        raise PlanningError(f"policy checkout is unavailable: {target.checkout}")
    if not target.remote or target.remote.startswith("-"):
        raise PlanningError("policy remote must be nonempty and must not begin with '-'")
    if not target.canonical_ref.startswith("refs/heads/"):
        raise PlanningError("policy canonical ref must be a full branch ref")
    path = PurePosixPath(target.path)
    if path.is_absolute() or ".." in path.parts or target.path != path.as_posix():
        raise PlanningError("policy path must be a normalized repository-relative path")
    listing = _git_output(
        target.checkout,
        ("ls-remote", target.remote, target.canonical_ref),
        "read current project-policy ref",
    )
    rows = [line.split() for line in listing.splitlines() if line.strip()]
    matches = [row for row in rows if len(row) == 2 and row[1] == target.canonical_ref]
    if len(matches) != 1 or not SHA_PATTERN.fullmatch(matches[0][0]):
        raise PlanningError("current project-policy ref is missing or ambiguous")
    commit = matches[0][0]
    fetched = run_git(
        target.checkout,
        ("fetch", "--no-tags", target.remote, commit),
    )
    _require_git(fetched, "fetch current project-policy commit")
    content = _git_output(
        target.checkout,
        ("show", f"{commit}:{target.path}"),
        "read current project policy",
    )
    with tempfile.TemporaryDirectory(prefix="atelier-policy-validate-") as temporary:
        policy_path = Path(temporary) / "policy.yaml"
        policy_path.write_text(content, encoding="utf-8")
        value = validate_project_policy(policy_path)
    repository = value["repository"]["identity"]
    if value["repository"]["canonical_ref"] != target.canonical_ref:
        raise PlanningError("policy target ref contradicts repository.canonical_ref")
    return _CurrentPolicy(
        value=value,
        repository=repository,
        commit=commit,
        path=target.path,
    )


def _validated_observation(
    path: Path,
    *,
    not_before: datetime,
    now: datetime | None,
) -> dict[str, Any]:
    try:
        return validate_observation(path, not_before=not_before, now=now)
    except HostBoundaryError as error:
        raise PlanningError(f"GitHub observation is not current and complete: {error}") from error


def _require_same_observation(
    expected: Mapping[str, Any],
    current: Mapping[str, Any],
) -> None:
    if _digest_json(expected) != _digest_json(current):
        raise MailboxTransitionRejected("GitHub observation changed during the transition")


def _require_initiative_digest(
    checkout: Path,
    initiative_id: str,
    expected_digest: str | None,
) -> None:
    path = checkout / _initiative_path(initiative_id)
    if not path.is_file():
        raise MailboxTransitionRejected(f"{initiative_id}: revised initiative does not exist")
    current_digest = _digest_bytes(path.read_bytes())
    if current_digest != expected_digest:
        raise MailboxTransitionRejected(
            f"{initiative_id}: expected initiative digest {expected_digest}, "
            f"found {current_digest}"
        )


def _require_preview_match(expected: PlanPreview, current: PlanPreview) -> None:
    _validate_preview(expected)
    if current != expected:
        raise MailboxTransitionRejected(
            f"{expected.work_id}: previewed work, policy, ticket, or authority changed"
        )


def _preview_token_value(preview: PlanPreview) -> dict[str, Any]:
    value = asdict(preview)
    del value["preview_digest"]
    return value


def _validate_preview(preview: PlanPreview) -> None:
    if preview.schema != "atelier.plan-preview/v1":
        raise PlanningError(f"unsupported preview schema {preview.schema!r}")
    if not isinstance(preview.work_id, str):
        raise PlanningError("preview work_id must be a string")
    _require_identifier(preview.work_id, "wrk")
    if type(preview.revision) is not int or preview.revision < 1:
        raise PlanningError("preview revision must be a positive integer")
    _require_text("preview.rendered_assignment", preview.rendered_assignment)
    if (preview.rendered_initiative is None) != (preview.initiative_digest is None):
        raise PlanningError("preview initiative content and digest must both be null or present")
    if preview.rendered_initiative is not None:
        _require_text("preview.rendered_initiative", preview.rendered_initiative)
    for name in (
        "work_digest",
        "ticket_observation_digest",
        "preview_digest",
    ):
        value = getattr(preview, name)
        if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
            raise PlanningError(f"preview {name} must be a lowercase SHA-256 digest")
    if (
        preview.initiative_digest is not None
        and (
            not isinstance(preview.initiative_digest, str)
            or DIGEST_PATTERN.fullmatch(preview.initiative_digest) is None
        )
    ):
        raise PlanningError("preview initiative_digest must be a lowercase SHA-256 digest")
    if (
        not isinstance(preview.policy_commit, str)
        or SHA_PATTERN.fullmatch(preview.policy_commit) is None
    ):
        raise PlanningError("preview policy_commit must be a lowercase Git SHA")
    _require_text("preview.ticket_repository", preview.ticket_repository)
    if type(preview.ticket_number) is not int or preview.ticket_number < 1:
        raise PlanningError("preview ticket_number must be a positive integer")
    ticket_match = (
        GITHUB_ISSUE_URL.fullmatch(preview.ticket_url)
        if isinstance(preview.ticket_url, str)
        else None
    )
    if (
        ticket_match is None
        or f"{ticket_match.group('owner')}/{ticket_match.group('repository')}"
        != preview.ticket_repository
        or int(ticket_match.group("number")) != preview.ticket_number
    ):
        raise PlanningError("preview ticket identity is contradictory")
    _require_text("preview.policy_repository", preview.policy_repository)
    _require_text("preview.policy_path", preview.policy_path)
    _validate_envelope(
        ApprovalEnvelope(preview.authority_ceiling, preview.required_evidence)
    )
    if _digest_bytes(preview.rendered_assignment.encode()) != preview.work_digest:
        raise PlanningError("preview rendered assignment does not match work_digest")
    if (
        preview.rendered_initiative is not None
        and _digest_bytes(preview.rendered_initiative.encode()) != preview.initiative_digest
    ):
        raise PlanningError("preview rendered initiative does not match initiative_digest")
    if _digest_json(_preview_token_value(preview)) != preview.preview_digest:
        raise PlanningError("preview digest does not match the complete preview")


def _ticket_material_digest(
    issue: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> str:
    relationships = {
        "parent": issue["parent"]["id"] if issue["parent"] else None,
        "sub_issues": sorted(item["id"] for item in issue["sub_issues"]),
        "blocked_by": sorted(item["id"] for item in issue["blocked_by"]),
        "blocking": sorted(item["id"] for item in issue["blocking"]),
    }
    available = {
        "body": issue["body"],
        "state": issue["state"],
        "relationships": relationships,
    }
    selected = {
        name: available[name]
        for name in policy["ticket"]["material_fields"]
    }
    return _digest_json(selected)


def _read_project(checkout: Path, project_id: str) -> dict[str, Any]:
    _require_identifier(project_id, "prj")
    path = checkout / f"projects/{project_id}/project.md"
    value, _ = _read_document(path)
    if value["id"] != project_id:
        raise PlanningError(f"{project_id}: project document identity mismatch")
    return value


def _read_document(path: Path) -> tuple[dict[str, Any], str]:
    try:
        return _read_yaml(path, frontmatter=True)
    except MailboxValidationError as error:
        raise PlanningError(str(error)) from error


def _render_work(assignment: AssignmentDraft, revision: int) -> str:
    value = {
        "schema": "atelier.work/v1",
        "id": assignment.id,
        "title": assignment.title,
        "project_id": assignment.project_id,
        "initiative_id": assignment.initiative_id,
        "status": "draft",
        "revision": revision,
        "dependencies": list(assignment.dependencies),
        "replaces": list(assignment.replaces),
        "native_ticket": {
            "provider": "github",
            "id": str(assignment.ticket_number),
            "url": assignment.ticket_url,
        },
        "approval": None,
        "claim": None,
        "blocking_message_id": None,
        "attempt_receipt_id": None,
        "delivery_receipt_id": None,
        "acceptance": None,
    }
    sections = [(name, getattr(assignment, name)) for name in SECTION_NAMES]
    return _render_document(value, _render_sections(sections))


def _render_initiative(initiative: InitiativeDraft) -> str:
    value = {
        "schema": "atelier.initiative/v1",
        "id": initiative.id,
        "title": initiative.title,
    }
    sections = [(name, getattr(initiative, name)) for name in INITIATIVE_SECTION_NAMES]
    return _render_document(value, _render_sections(sections))


def _render_document(frontmatter: Mapping[str, Any], body: str) -> str:
    encoded = yaml.safe_dump(
        dict(frontmatter),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    )
    return f"---\n{encoded}---\n{body.rstrip()}\n"


def _render_sections(sections: Sequence[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"## {name.replace('_', ' ').title()}\n\n{value.strip()}"
        for name, value in sections
    )


def _validate_assignment_input(assignment: AssignmentDraft) -> None:
    _require_identifier(assignment.id, "wrk")
    _require_identifier(assignment.project_id, "prj")
    if assignment.initiative_id is not None:
        _require_identifier(assignment.initiative_id, "ini")
    for identifier in (*assignment.dependencies, *assignment.replaces):
        _require_identifier(identifier, "wrk")
    if assignment.id in assignment.dependencies or assignment.id in assignment.replaces:
        raise PlanningError("assignment cannot depend on or replace itself")
    if len(set(assignment.dependencies)) != len(assignment.dependencies):
        raise PlanningError("assignment dependencies must be unique")
    if len(set(assignment.replaces)) != len(assignment.replaces):
        raise PlanningError("assignment replacement targets must be unique")
    if assignment.ticket_number < 1:
        raise PlanningError("GitHub ticket number must be positive")
    _require_text("assignment.title", assignment.title)
    for name in SECTION_NAMES:
        _require_text(f"assignment.{name}", getattr(assignment, name))


def _validate_initiative_input(
    initiative: InitiativeDraft | None,
    assignment_initiative_id: str | None,
) -> None:
    if initiative is None:
        return
    _require_identifier(initiative.id, "ini")
    if initiative.id != assignment_initiative_id:
        raise PlanningError("initiative identity does not match assignment.initiative_id")
    _require_text("initiative.title", initiative.title)
    for name in INITIATIVE_SECTION_NAMES:
        _require_text(f"initiative.{name}", getattr(initiative, name))


def _validate_envelope(envelope: ApprovalEnvelope) -> None:
    if len(set(envelope.authority_ceiling)) != len(envelope.authority_ceiling):
        raise PlanningError("approval authority actions must be unique")
    if len(set(envelope.required_evidence)) != len(envelope.required_evidence):
        raise PlanningError("approval evidence names must be unique")
    unknown_actions = set(envelope.authority_ceiling) - AUTHORITY_ACTIONS
    if unknown_actions:
        raise PlanningError(
            f"unsupported approval authority: {', '.join(sorted(unknown_actions))}"
        )
    unknown_evidence = set(envelope.required_evidence) - EVIDENCE_NAMES
    if unknown_evidence:
        raise PlanningError(
            f"unsupported approval evidence: {', '.join(sorted(unknown_evidence))}"
        )
    if not envelope.required_evidence:
        raise PlanningError("approval must require at least one evidence predicate")


def _require_identifier(value: str, prefix: str) -> None:
    match = ID_PATTERN.fullmatch(value)
    if match is None or match.group("prefix") != prefix:
        raise PlanningError(f"{value!r} is not a valid {prefix} identifier")


def _require_expected_revision(value: Any) -> None:
    if type(value) is not int or value < 1:
        raise PlanningError("expected revision must be a positive integer")


def _require_text(label: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PlanningError(f"{label} must not be empty")


def _work_path(work_id: str) -> str:
    return f"work/{work_id}/work.md"


def _initiative_path(initiative_id: str) -> str:
    return f"initiatives/{initiative_id}/initiative.md"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _digest_bytes(encoded)


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_git(result: Any, operation: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise PlanningError(f"{operation}: {detail}")


def _git_output(cwd: Path, arguments: Sequence[str], operation: str) -> str:
    result = run_git(cwd, arguments)
    _require_git(result, operation)
    return result.stdout.strip()


def _planning_result(
    result: WriteResult,
    work_id: str,
    revision: int,
    status: str,
) -> PlanningResult:
    return PlanningResult(
        operation=result.operation,
        work_id=work_id,
        revision=revision,
        status=status,
        commit=result.commit,
        base_revision=result.base_revision,
        branch=result.branch,
        attempts=result.attempts,
        recovered=result.recovered,
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PlanningError(f"invalid timestamp {value!r}") from error
    if parsed.utcoffset() is None:
        raise PlanningError("timestamp must include a UTC offset")
    return parsed


def _read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlanningError(f"request is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise PlanningError("request must be a JSON object")
    return value


def _assignment(value: Mapping[str, Any]) -> AssignmentDraft:
    return AssignmentDraft(
        id=value["id"],
        title=value["title"],
        project_id=value["project_id"],
        initiative_id=value.get("initiative_id"),
        dependencies=tuple(value.get("dependencies", [])),
        replaces=tuple(value.get("replaces", [])),
        ticket_number=value["ticket_number"],
        ticket_url=value["ticket_url"],
        **{name: value[name] for name in SECTION_NAMES},
    )


def _initiative(value: Mapping[str, Any] | None) -> InitiativeDraft | None:
    if value is None:
        return None
    return InitiativeDraft(
        id=value["id"],
        title=value["title"],
        **{name: value[name] for name in INITIATIVE_SECTION_NAMES},
    )


def _envelope(value: Mapping[str, Any]) -> ApprovalEnvelope:
    return ApprovalEnvelope(
        authority_ceiling=tuple(value["authority_ceiling"]),
        required_evidence=tuple(value["required_evidence"]),
    )


def _policy_target(value: Mapping[str, Any]) -> PolicyTarget:
    return PolicyTarget(
        checkout=Path(value["checkout"]),
        remote=value["remote"],
        canonical_ref=value["canonical_ref"],
        path=value["path"],
    )


def _preview(value: Mapping[str, Any]) -> PlanPreview:
    expected_fields = {field.name for field in fields(PlanPreview)}
    actual_fields = set(value)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        unknown = sorted(actual_fields - expected_fields)
        raise PlanningError(
            f"preview fields do not match atelier.plan-preview/v1; "
            f"missing={missing}, unknown={unknown}"
        )
    if not isinstance(value["authority_ceiling"], list) or not all(
        isinstance(item, str) for item in value["authority_ceiling"]
    ):
        raise PlanningError("preview authority_ceiling must be an array of strings")
    if not isinstance(value["required_evidence"], list) or not all(
        isinstance(item, str) for item in value["required_evidence"]
    ):
        raise PlanningError("preview required_evidence must be an array of strings")
    normalized = dict(value)
    normalized["authority_ceiling"] = tuple(value["authority_ceiling"])
    normalized["required_evidence"] = tuple(value["required_evidence"])
    preview = PlanPreview(**normalized)
    _validate_preview(preview)
    return preview


def _common_request(value: Mapping[str, Any]) -> tuple[Planner, Path, datetime]:
    planner = Planner(
        value["mailbox"]["remote"],
        value["mailbox"]["canonical_branch"],
        max_attempts=value["mailbox"].get("max_attempts", 3),
    )
    return (
        planner,
        Path(value["observation"]["path"]),
        _parse_timestamp(value["observation"]["not_before"]),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    identifier = subparsers.add_parser("new-id")
    identifier.add_argument("prefix", choices=("ini", "wrk"))
    for name in ("create", "revise", "preview", "approve"):
        command = subparsers.add_parser(name)
        command.add_argument("request", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "new-id":
        print(new_identifier(args.prefix))
        return 0
    try:
        request = _read_request(args.request)
        planner, observation_path, not_before = _common_request(request)
        if args.command == "create":
            result: Any = planner.create_draft(
                _assignment(request["assignment"]),
                initiative=_initiative(request.get("initiative")),
                observation_path=observation_path,
                observation_not_before=not_before,
            )
        elif args.command == "revise":
            result = planner.revise_draft(
                _assignment(request["assignment"]),
                expected_revision=request["expected_revision"],
                initiative=_initiative(request.get("initiative")),
                expected_initiative_digest=request.get("expected_initiative_digest"),
                observation_path=observation_path,
                observation_not_before=not_before,
            )
        elif args.command == "preview":
            result = planner.preview_approval(
                request["work_id"],
                expected_revision=request["expected_revision"],
                envelope=_envelope(request["envelope"]),
                policy_target=_policy_target(request["policy"]),
                observation_path=observation_path,
                observation_not_before=not_before,
            )
        else:
            result = planner.approve(
                _preview(request["preview"]),
                approved_by=request["approved_by"],
                approved_at=_parse_timestamp(request["approved_at"]),
                policy_target=_policy_target(request["policy"]),
                observation_path=observation_path,
                observation_not_before=not_before,
            )
        print(json.dumps(asdict(result), indent=2, sort_keys=True, default=str))
        return 0
    except (
        KeyError,
        TypeError,
        PlanningError,
        MailboxWriteError,
        MailboxTransitionRejected,
        MailboxValidationError,
        ValueError,
    ) as error:
        print(f"planning failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
