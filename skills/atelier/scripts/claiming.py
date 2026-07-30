#!/usr/bin/env python3
"""Claim Atelier work and persist claim-fenced checkpoint and handoff transitions."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from skills.atelier.scripts.host_boundary import HostBoundaryError, check_host
from skills.atelier.scripts.identifiers import new_identifier
from skills.atelier.scripts.mailbox import (
    MailboxValidationError,
    _github_remote_url,
    _valid_branch_ref,
    validate_project_policy,
)
from skills.atelier.scripts.planning import (
    PolicyTarget,
    _CurrentPolicy,
    _git_output,
    _read_current_policy,
    _read_document,
    _read_project,
    _render_document,
    _require_git,
    _require_work_ticket,
    _ticket_material_digest,
    _validated_observation,
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
CANDIDATE_REQUIRED_ACTIONS = frozenset(
    {
        "repository.candidate.push",
        "pull_request.create",
        "pull_request.update",
        "review.reply",
        "review.resolve",
    }
)
ID_PATTERN = re.compile(
    r"^(?P<prefix>clm|msg|rcp|run|wrk)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ACTIVE_STATES = frozenset({"active", "blocked", "delivered"})


class ClaimingError(RuntimeError):
    """A claim or checkpoint transition cannot be trusted or safely applied."""


@dataclass(frozen=True)
class ClaimFence:
    """The exact current claim-ledger tail required by a worker transition."""

    claim_id: str
    worker_run_id: str
    sequence: int
    continuation_token: str


@dataclass(frozen=True)
class HostTarget:
    """The exact installed capability and read-only connector boundary to prove."""

    descriptor_path: Path
    skill_name: str
    skill_root: Path
    connector: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointRequest:
    """One proposed delegated-execution checkpoint transition."""

    fence: ClaimFence
    phase: str
    action: str
    proposed_effect_digest: str
    candidate_head: str | None
    candidate_remote_ref: str | None
    acknowledged_candidate_head: str | None
    next_continuation_token: str
    recorded_at: datetime
    candidate: Mapping[str, Any] | None = None
    ticket_observation_digest: str | None = None


@dataclass(frozen=True)
class AttemptEvidence:
    """Evidence copied into one blocked, released, or takeover receipt."""

    validation: tuple[Mapping[str, Any], ...] = ()
    reviews: tuple[Mapping[str, Any], ...] = ()
    unresolved_obligations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimResult:
    """One verified canonical claim-coordination transition."""

    operation: str
    work_id: str
    status: str
    claim_id: str | None
    worker_run_id: str | None
    sequence: int | None
    continuation_token: str | None
    commit: str
    base_revision: str
    branch: str
    attempts: int
    recovered: bool


@dataclass(frozen=True)
class _ExecutionState:
    work: dict[str, Any]
    body: str
    project: dict[str, Any]
    approved_commit: str
    approved_policy: dict[str, Any]
    current_policy: _CurrentPolicy
    effective_policy: dict[str, Any]
    observation: dict[str, Any]
    ticket_digest: str


CandidateVerifier = Callable[[Mapping[str, Any]], bool]
CapabilityVerifier = Callable[[HostTarget], bool]
PolicyRemoteVerifier = Callable[[PolicyTarget, str], bool]


class ClaimCoordinator:
    """Production claim and checkpoint transitions over one canonical Git mailbox."""

    def __init__(
        self,
        remote: str,
        branch: str,
        *,
        max_attempts: int = 3,
        writer: GitMailboxWriter | None = None,
        candidate_verifier: CandidateVerifier | None = None,
        capability_verifier: CapabilityVerifier | None = None,
        policy_remote_verifier: PolicyRemoteVerifier | None = None,
    ):
        if not remote or remote.startswith("-"):
            raise ClaimingError("mailbox remote must be nonempty and must not begin with '-'")
        self.remote = remote
        self.branch = branch
        self.writer = writer or GitMailboxWriter(remote, branch, max_attempts=max_attempts)
        self.candidate_verifier = candidate_verifier or _candidate_remote_reachable
        self.capability_verifier = capability_verifier or _capability_compatible
        self.policy_remote_verifier = policy_remote_verifier or _policy_remote_matches_repository

    def claim(
        self,
        work_id: str,
        *,
        claim_id: str,
        worker_run_id: str,
        continuation_token: str,
        approved_commit: str,
        claimed_at: datetime,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None = None,
    ) -> ClaimResult:
        """Atomically claim one currently ready project-serial assignment."""
        _require_identifier(work_id, "wrk")
        _require_identifier(claim_id, "clm")
        _require_identifier(worker_run_id, "run")
        _require_sha(approved_commit, "approved_commit")
        _require_token(continuation_token, "continuation_token")
        _require_timestamp(claimed_at, "claimed_at")
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            self._verify_capability(host_target)
            state = self._execution_state(
                context,
                work_id,
                approved_commit=approved_commit,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )
            work = state.work
            if work["status"] != "approved" or work["claim"] is not None:
                raise MailboxTransitionRejected(f"{work_id}: work is not unclaimed and approved")
            status_by_work = {item["id"]: item["status"] for item in context.snapshot["work"]}
            unresolved = [
                dependency
                for dependency in work["dependencies"]
                if status_by_work.get(dependency) != "accepted"
            ]
            if unresolved:
                raise MailboxTransitionRejected(
                    f"{work_id}: dependencies are not accepted: {', '.join(unresolved)}"
                )
            active = [
                item["id"]
                for item in context.snapshot["work"]
                if item["id"] != work_id
                and item["project_id"] == work["project_id"]
                and item["status"] in ACTIVE_STATES
            ]
            if active:
                raise MailboxTransitionRejected(
                    f"{work_id}: project already has active work: {', '.join(active)}"
                )
            candidate, inherited_receipt_id = self._released_candidate(context, work)
            planned.clear()
            planned.update(
                state=state,
                claim={
                    "id": claim_id,
                    "worker_run_id": worker_run_id,
                    "inherited_receipt_id": inherited_receipt_id,
                    "work_revision": work["revision"],
                    "approved_commit": approved_commit,
                    "policy_commit": state.current_policy.commit,
                    "ticket_observation_digest": state.ticket_digest,
                    "invocation_digest": None,
                    "claimed_at": _timestamp(claimed_at),
                    "host": "codex",
                    "checkpoint": {
                        "sequence": 0,
                        "continuation_token": continuation_token,
                        "authorizations": [],
                    },
                    "candidate": candidate,
                },
            )

        def plan(context: TransitionContext) -> TransitionPlan:
            state: _ExecutionState = planned["state"]
            work = copy.deepcopy(state.work)
            work["status"] = "active"
            work["claim"] = copy.deepcopy(planned["claim"])
            work["blocking_message_id"] = None
            work["delivery_receipt_id"] = None
            work["acceptance"] = None
            return TransitionPlan(
                commit_message=f"claim {work_id}",
                changes=(FileChange(_work_path(work_id), _render_document(work, state.body)),),
            )

        result = self.writer.publish("claim", revalidate=revalidate, plan=plan)
        return _claim_result(result, work_id, "active", planned["claim"])

    def authorize(
        self,
        work_id: str,
        request: CheckpointRequest,
        *,
        approved_commit: str,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None = None,
        state_revalidator: Callable[[_ExecutionState], None] | None = None,
    ) -> ClaimResult:
        """Allow one exact external action or acknowledge one exact published candidate."""
        _require_identifier(work_id, "wrk")
        _validate_checkpoint_request(request)
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            self._verify_capability(host_target)
            state = self._execution_state(
                context,
                work_id,
                approved_commit=approved_commit,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )
            if state_revalidator is not None:
                state_revalidator(state)
            if state.work["status"] != "active":
                raise MailboxTransitionRejected(f"{work_id}: checkpoints require active work")
            claim = _require_fence(state.work, request.fence)
            if claim["approved_commit"] != approved_commit:
                raise MailboxTransitionRejected(f"{work_id}: claim approved commit changed")
            if claim["ticket_observation_digest"] != state.ticket_digest:
                raise MailboxTransitionRejected(
                    f"{work_id}: material ticket observation changed during the invocation"
                )
            if (
                request.ticket_observation_digest is not None
                and request.ticket_observation_digest != state.ticket_digest
            ):
                raise MailboxTransitionRejected(
                    f"{work_id}: checkpoint ticket observation is not current"
                )
            effective_authority = set(state.effective_policy["authority"]["allow"])
            approved_authority = set(state.work["approval"]["authority_ceiling"])
            if request.action not in effective_authority & approved_authority:
                raise MailboxTransitionRejected(
                    f"{work_id}: action {request.action!r} exceeds effective authority"
                )
            updated_claim = copy.deepcopy(claim)
            self._apply_checkpoint(updated_claim, request)
            planned.clear()
            planned.update(state=state, claim=updated_claim)

        def plan(context: TransitionContext) -> TransitionPlan:
            state: _ExecutionState = planned["state"]
            work = copy.deepcopy(state.work)
            work["claim"] = copy.deepcopy(planned["claim"])
            return TransitionPlan(
                commit_message=(
                    f"record {request.phase} checkpoint {request.fence.sequence + 1} for {work_id}"
                ),
                changes=(FileChange(_work_path(work_id), _render_document(work, state.body)),),
            )

        result = self.writer.publish("checkpoint", revalidate=revalidate, plan=plan)
        return _claim_result(result, work_id, "active", planned["claim"])

    def block(
        self,
        work_id: str,
        fence: ClaimFence,
        *,
        message_id: str,
        receipt_id: str,
        subject: str,
        detail: str,
        created_at: datetime,
        evidence: AttemptEvidence | None = None,
    ) -> ClaimResult:
        """Persist one exact worker blocker and retained attempt receipt."""
        _require_identifier(work_id, "wrk")
        _require_identifier(message_id, "msg")
        _require_identifier(receipt_id, "rcp")
        _require_text(subject, "subject")
        _require_text(detail, "detail")
        _require_timestamp(created_at, "created_at")
        evidence = evidence or AttemptEvidence()
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            work, body = _read_work(context.checkout, work_id)
            if work["status"] != "active":
                raise MailboxTransitionRejected(f"{work_id}: only active work can be blocked")
            claim = _require_fence(work, fence)
            self._verify_candidate(claim["candidate"])
            receipt = _attempt_receipt(
                work,
                claim,
                receipt_id=receipt_id,
                outcome="blocked",
                mutation_ownership="retained",
                ended_at=created_at,
                evidence=evidence,
            )
            message = {
                "schema": "atelier.message/v1",
                "id": message_id,
                "work_id": work_id,
                "kind": "needs-decision",
                "author_role": "worker",
                "worker_run_id": claim["worker_run_id"],
                "audience": "planner",
                "in_reply_to": None,
                "resolves": None,
                "blocks": "worker",
                "created_at": _timestamp(created_at),
                "subject": subject,
            }
            planned.clear()
            planned.update(work=work, body=body, claim=claim, receipt=receipt, message=message)

        def plan(context: TransitionContext) -> TransitionPlan:
            work = copy.deepcopy(planned["work"])
            work["status"] = "blocked"
            work["blocking_message_id"] = message_id
            work["attempt_receipt_id"] = receipt_id
            return TransitionPlan(
                commit_message=f"block {work_id}",
                changes=(
                    FileChange(
                        _message_path(work_id, message_id),
                        _render_document(planned["message"], detail),
                    ),
                    FileChange(
                        _receipt_path(work_id, receipt_id),
                        _render_document(planned["receipt"], detail),
                    ),
                    FileChange(_work_path(work_id), _render_document(work, planned["body"])),
                ),
            )

        result = self.writer.publish("block", revalidate=revalidate, plan=plan)
        return _claim_result(result, work_id, "blocked", planned["claim"])

    def release(
        self,
        work_id: str,
        fence: ClaimFence,
        *,
        receipt_id: str,
        reason: str,
        ended_at: datetime,
        evidence: AttemptEvidence | None = None,
    ) -> ClaimResult:
        """Release one exact claim while preserving its authoritative handoff receipt."""
        _require_identifier(work_id, "wrk")
        _require_identifier(receipt_id, "rcp")
        _require_text(reason, "reason")
        _require_timestamp(ended_at, "ended_at")
        evidence = evidence or AttemptEvidence()
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            work, body = _read_work(context.checkout, work_id)
            if work["status"] not in ACTIVE_STATES:
                raise MailboxTransitionRejected(f"{work_id}: work has no releasable claim")
            claim = _require_fence(work, fence)
            self._verify_candidate(claim["candidate"])
            receipt = _attempt_receipt(
                work,
                claim,
                receipt_id=receipt_id,
                outcome="released",
                mutation_ownership="relinquished",
                ended_at=ended_at,
                evidence=evidence,
            )
            planned.clear()
            planned.update(work=work, body=body, receipt=receipt)

        def plan(context: TransitionContext) -> TransitionPlan:
            work = copy.deepcopy(planned["work"])
            work["status"] = "approved"
            work["claim"] = None
            work["blocking_message_id"] = None
            work["attempt_receipt_id"] = receipt_id
            work["delivery_receipt_id"] = None
            work["acceptance"] = None
            return TransitionPlan(
                commit_message=f"release {work_id}",
                changes=(
                    FileChange(
                        _receipt_path(work_id, receipt_id),
                        _render_document(planned["receipt"], reason),
                    ),
                    FileChange(_work_path(work_id), _render_document(work, planned["body"])),
                ),
            )

        result = self.writer.publish("release", revalidate=revalidate, plan=plan)
        return _claim_result(result, work_id, "approved", None)

    def takeover(
        self,
        work_id: str,
        replaced_fence: ClaimFence,
        *,
        claim_id: str,
        worker_run_id: str,
        continuation_token: str,
        takeover_message_id: str,
        takeover_receipt_id: str | None = None,
        reason: str,
        taken_over_at: datetime,
        approved_commit: str,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None = None,
    ) -> ClaimResult:
        """Replace one exact current claim without discarding its candidate or history."""
        _require_identifier(work_id, "wrk")
        _require_identifier(claim_id, "clm")
        _require_identifier(worker_run_id, "run")
        _require_identifier(takeover_message_id, "msg")
        if takeover_receipt_id is not None:
            _require_identifier(takeover_receipt_id, "rcp")
        _require_token(continuation_token, "continuation_token")
        _require_text(reason, "reason")
        _require_timestamp(taken_over_at, "taken_over_at")
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            self._verify_capability(host_target)
            state = self._execution_state(
                context,
                work_id,
                approved_commit=approved_commit,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )
            if state.work["status"] not in ACTIVE_STATES:
                raise MailboxTransitionRejected(f"{work_id}: work has no replaceable claim")
            prior_claim = _require_fence(state.work, replaced_fence)
            if prior_claim["id"] == claim_id or prior_claim["worker_run_id"] == worker_run_id:
                raise MailboxTransitionRejected(
                    f"{work_id}: takeover requires fresh claim identities"
                )
            self._verify_candidate(prior_claim["candidate"])
            new_claim = {
                "id": claim_id,
                "worker_run_id": worker_run_id,
                "inherited_receipt_id": None,
                "work_revision": state.work["revision"],
                "approved_commit": approved_commit,
                "policy_commit": state.current_policy.commit,
                "ticket_observation_digest": state.ticket_digest,
                "invocation_digest": None,
                "claimed_at": _timestamp(taken_over_at),
                "host": "codex",
                "checkpoint": {
                    "sequence": 0,
                    "continuation_token": continuation_token,
                    "authorizations": [],
                },
                "candidate": copy.deepcopy(prior_claim["candidate"]),
            }
            current_status = state.work["status"]
            takeover_status = "active" if current_status == "delivered" else current_status
            takeover_receipt = None
            if current_status == "active":
                if takeover_receipt_id is None:
                    raise MailboxTransitionRejected(
                        f"{work_id}: active takeover requires a stable receipt identity"
                    )
                takeover_receipt = _attempt_receipt(
                    state.work,
                    prior_claim,
                    receipt_id=takeover_receipt_id,
                    outcome="released",
                    mutation_ownership="relinquished",
                    ended_at=taken_over_at,
                    evidence=AttemptEvidence(),
                )
            if prior_claim["candidate"] is not None:
                inherited_receipt_id = (
                    takeover_receipt_id
                    if current_status == "active"
                    else state.work["attempt_receipt_id"]
                )
                if inherited_receipt_id is None:
                    raise MailboxTransitionRejected(
                        f"{work_id}: takeover candidate lacks a predecessor receipt"
                    )
                new_claim["inherited_receipt_id"] = inherited_receipt_id
            current_blocker = state.work["blocking_message_id"]
            takeover_message = {
                "schema": "atelier.message/v1",
                "id": takeover_message_id,
                "work_id": work_id,
                "kind": "notification",
                "author_role": "planner",
                "worker_run_id": None,
                "audience": "worker",
                "in_reply_to": current_blocker,
                "resolves": None,
                "blocks": None,
                "created_at": _timestamp(taken_over_at),
                "subject": "Claim taken over",
            }
            planned.clear()
            planned.update(
                state=state,
                claim=new_claim,
                takeover_message=takeover_message,
                takeover_receipt=takeover_receipt,
                status=takeover_status,
            )

        def plan(context: TransitionContext) -> TransitionPlan:
            state: _ExecutionState = planned["state"]
            work = copy.deepcopy(state.work)
            work["status"] = planned["status"]
            work["claim"] = copy.deepcopy(planned["claim"])
            work["blocking_message_id"] = state.work["blocking_message_id"]
            work["delivery_receipt_id"] = None
            work["acceptance"] = None
            changes = [
                FileChange(
                    _message_path(work_id, takeover_message_id),
                    _render_document(planned["takeover_message"], reason),
                ),
                FileChange(_work_path(work_id), _render_document(work, state.body)),
            ]
            if planned["takeover_receipt"] is not None:
                work["attempt_receipt_id"] = takeover_receipt_id
                changes = [
                    FileChange(
                        _receipt_path(work_id, takeover_receipt_id),
                        _render_document(planned["takeover_receipt"], reason),
                    ),
                    FileChange(
                        _message_path(work_id, takeover_message_id),
                        _render_document(planned["takeover_message"], reason),
                    ),
                    FileChange(_work_path(work_id), _render_document(work, state.body)),
                ]
            return TransitionPlan(
                commit_message=f"take over {work_id}",
                changes=tuple(changes),
            )

        result = self.writer.publish("takeover", revalidate=revalidate, plan=plan)
        return _claim_result(result, work_id, planned["status"], planned["claim"])

    def _execution_state(
        self,
        context: TransitionContext,
        work_id: str,
        *,
        approved_commit: str,
        policy_target: PolicyTarget,
        observation_path: Path,
        observation_not_before: datetime,
        now: datetime | None,
    ) -> _ExecutionState:
        work, body = _read_work(context.checkout, work_id)
        approval = work["approval"]
        if approval is None or approval["revision"] != work["revision"]:
            raise MailboxTransitionRejected(f"{work_id}: work has no current approval")
        self._require_approved_commit(context, work_id, work, body, approved_commit)
        project = _read_project(context.checkout, work["project_id"])
        if not self.policy_remote_verifier(policy_target, project["repository"]):
            raise MailboxTransitionRejected(
                "policy remote is foreign or unverifiable for the managed project"
            )
        observation = _validated_observation(
            observation_path,
            not_before=observation_not_before,
            now=now,
        )
        _require_work_ticket(work, project, observation)
        approved_policy = _read_policy_at_commit(policy_target, approval["policy"]["commit"])
        current_policy = _read_current_policy(policy_target)
        effective_policy = _effective_policy(approved_policy, current_policy.value)
        _require_policy_identity(
            effective_policy,
            current_policy,
            project=project,
            work=work,
            mailbox_remote=self.remote,
            mailbox_branch=self.branch,
            mailbox_realm=context.snapshot["realm_id"],
            approval=approval,
        )
        issue = observation["issue"]
        if issue["state"].lower() not in effective_policy["ticket"]["allowed_states"]:
            raise MailboxTransitionRejected(f"ticket #{issue['number']} is not in an allowed state")
        if effective_policy["ticket"]["require_no_blockers"]:
            blockers = [item for item in issue["blocked_by"] if item["state"] != "CLOSED"]
            if blockers:
                numbers = ", ".join(f"#{item['number']}" for item in blockers)
                raise MailboxTransitionRejected(
                    f"ticket #{issue['number']} has unresolved blockers: {numbers}"
                )
        ticket_digest = _ticket_material_digest(issue, effective_policy)
        return _ExecutionState(
            work=work,
            body=body,
            project=project,
            approved_commit=approved_commit,
            approved_policy=approved_policy,
            current_policy=current_policy,
            effective_policy=effective_policy,
            observation=observation,
            ticket_digest=ticket_digest,
        )

    def _require_approved_commit(
        self,
        context: TransitionContext,
        work_id: str,
        work: Mapping[str, Any],
        body: str,
        approved_commit: str,
    ) -> None:
        _require_sha(approved_commit, "approved_commit")
        with tempfile.TemporaryDirectory(prefix="atelier-approval-history-") as temporary:
            history = Path(temporary) / "mailbox"
            cloned = run_git(
                None,
                (
                    "clone",
                    "--no-checkout",
                    "--branch",
                    self.branch,
                    self.remote,
                    str(history),
                ),
            )
            _require_git(cloned, "read canonical mailbox approval history")
            ancestor = run_git(
                history,
                ("merge-base", "--is-ancestor", approved_commit, context.base_revision),
            )
            if ancestor.returncode != 0:
                raise MailboxTransitionRejected(
                    f"{work_id}: approved commit is not in canonical mailbox history"
                )
            approved_work, approved_body = _read_work_at(
                history, approved_commit, _work_path(work_id)
            )
            if _approved_contract(approved_work, approved_body) != _approved_contract(work, body):
                raise MailboxTransitionRejected(
                    f"{work_id}: approved commit does not contain the current approved contract"
                )
            parent = run_git(history, ("rev-parse", f"{approved_commit}^"))
            if parent.returncode == 0:
                try:
                    parent_work, parent_body = _read_work_at(
                        history, parent.stdout.strip(), _work_path(work_id)
                    )
                except ClaimingError:
                    pass
                else:
                    if _approved_contract(parent_work, parent_body) == _approved_contract(
                        approved_work, approved_body
                    ):
                        raise MailboxTransitionRejected(
                            f"{work_id}: supplied approved commit is not the approval transition"
                        )

    def _released_candidate(
        self,
        context: TransitionContext,
        work: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        receipt_id = work["attempt_receipt_id"]
        if receipt_id is None:
            return None, None
        receipt, _ = _read_document(context.checkout / _receipt_path(work["id"], receipt_id))
        if receipt["outcome"] != "released":
            raise MailboxTransitionRejected(
                f"{work['id']}: approved work attempt is not a released receipt"
            )
        candidate = receipt["candidate"] if receipt["handoff"] == "transferable" else None
        self._verify_candidate(candidate)
        return copy.deepcopy(candidate), receipt_id if candidate is not None else None

    def _apply_checkpoint(
        self,
        claim: dict[str, Any],
        request: CheckpointRequest,
    ) -> None:
        ledger = claim["checkpoint"]["authorizations"]
        candidate = copy.deepcopy(request.candidate) if request.candidate is not None else None
        if request.phase == "candidate_published":
            if (
                request.action != "repository.candidate.push"
                or request.candidate_head is None
                or request.candidate_remote_ref is None
                or request.acknowledged_candidate_head != request.candidate_head
                or candidate is None
                or candidate.get("head_revision") != request.candidate_head
                or candidate.get("remote_ref") != request.candidate_remote_ref
            ):
                raise MailboxTransitionRejected(
                    "candidate publication must acknowledge one exact repository candidate push"
                )
            if not ledger:
                raise MailboxTransitionRejected(
                    "candidate publication has no preceding push authorization"
                )
            prior = ledger[-1]
            if (
                prior["phase"] != "pre_external_mutation"
                or prior["action"] != "repository.candidate.push"
                or prior["candidate_head"] != request.candidate_head
                or prior["candidate_remote_ref"] != request.candidate_remote_ref
                or prior["proposed_effect_digest"] != request.proposed_effect_digest
            ):
                raise MailboxTransitionRejected(
                    "candidate publication does not match the preceding push authorization"
                )
            current_candidate = claim["candidate"]
            current_pull_request = (
                current_candidate["pull_request"] if current_candidate is not None else None
            )
            same_candidate_lineage = current_candidate is not None and (
                candidate["repository"],
                candidate["remote"],
                candidate["remote_url"],
                candidate["remote_ref"],
                candidate["base_revision"],
            ) == (
                current_candidate["repository"],
                current_candidate["remote"],
                current_candidate["remote_url"],
                current_candidate["remote_ref"],
                current_candidate["base_revision"],
            )
            retained_pull_request = (
                candidate["pull_request"] is not None
                and candidate["pull_request"] == current_pull_request
                and same_candidate_lineage
            )
            pull_request_requires_authority = (
                candidate["pull_request"] != current_pull_request
                or (candidate["pull_request"] is not None and not retained_pull_request)
            )
            if pull_request_requires_authority and not _pull_request_mutation_authorized(
                claim,
                candidate_head=request.candidate_head,
                candidate_remote_ref=request.candidate_remote_ref,
            ):
                raise MailboxTransitionRejected(
                    "candidate pull request metadata lacks exact pre-mutation authority"
                )
            self._verify_candidate(candidate)
            claim["candidate"] = candidate
        else:
            if request.acknowledged_candidate_head is not None:
                raise MailboxTransitionRejected(
                    "pre-mutation checkpoint cannot acknowledge a candidate"
                )
            if request.action in CANDIDATE_REQUIRED_ACTIONS and (
                request.candidate_head is None or request.candidate_remote_ref is None
            ):
                raise MailboxTransitionRejected(
                    f"action {request.action!r} requires an exact candidate head and remote ref"
                )
            current_head = (
                claim["candidate"]["head_revision"] if claim["candidate"] is not None else None
            )
            current_ref = (
                claim["candidate"]["remote_ref"] if claim["candidate"] is not None else None
            )
            if (
                request.action in CANDIDATE_REQUIRED_ACTIONS
                and request.action != "repository.candidate.push"
                and (
                    request.candidate_head != current_head
                    or request.candidate_remote_ref != current_ref
                )
            ):
                raise MailboxTransitionRejected(
                    f"action {request.action!r} does not name the acknowledged candidate"
                )
            if current_head is not None:
                self._verify_candidate(claim["candidate"])
        next_sequence = request.fence.sequence + 1
        ledger.append(
            {
                "sequence": next_sequence,
                "invocation_id": request.fence.worker_run_id,
                "phase": request.phase,
                "action": request.action,
                "proposed_effect_digest": request.proposed_effect_digest,
                "candidate_head": request.candidate_head,
                "candidate_remote_ref": request.candidate_remote_ref,
                "candidate_pull_request": (
                    candidate["pull_request"] if request.phase == "candidate_published" else None
                ),
                "acknowledged_candidate_head": request.acknowledged_candidate_head,
                "recorded_at": _timestamp(request.recorded_at),
            }
        )
        claim["checkpoint"]["sequence"] = next_sequence
        claim["checkpoint"]["continuation_token"] = request.next_continuation_token

    def _verify_capability(self, target: HostTarget) -> None:
        if not self.capability_verifier(target):
            raise ClaimingError("required delegated implement-ticket capability is unavailable")

    def _verify_candidate(self, candidate: Mapping[str, Any] | None) -> None:
        if candidate is not None and not self.candidate_verifier(candidate):
            raise MailboxTransitionRejected(
                "candidate is not reachable at its exact declared remote ref and head"
            )



def _pull_request_mutation_authorized(
    claim: Mapping[str, Any],
    *,
    candidate_head: str | None,
    candidate_remote_ref: str | None,
) -> bool:
    if candidate_head is None or candidate_remote_ref is None:
        return False
    ledger = claim["checkpoint"]["authorizations"]
    prior_publication_sequence = max(
        (
            entry["sequence"]
            for entry in ledger
            if entry["phase"] == "candidate_published"
        ),
        default=0,
    )
    return any(
        entry["sequence"] > prior_publication_sequence
        and entry["phase"] == "pre_external_mutation"
        and entry["action"] in {"pull_request.create", "pull_request.update"}
        and entry["candidate_head"] == candidate_head
        and entry["candidate_remote_ref"] == candidate_remote_ref
        for entry in ledger
    )


def _effective_policy(
    approved: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    invariant_paths = (
        ("schema",),
        ("mailbox", "remote"),
        ("mailbox", "realm_id"),
        ("mailbox", "canonical_branch"),
        ("mailbox", "project_id"),
        ("repository", "identity"),
        ("repository", "canonical_ref"),
        ("ticket", "provider"),
        ("execution", "capability"),
        ("execution", "delivery_outcome"),
        ("execution", "parallel_assignments"),
        ("acceptance", "actor"),
    )
    for path in invariant_paths:
        if _at(approved, path) != _at(current, path):
            raise MailboxTransitionRejected(
                f"approved and current policies are incompatible at {'.'.join(path)}"
            )
    effective = copy.deepcopy(current)
    effective["authority"]["allow"] = _ordered_intersection(
        approved["authority"]["allow"], current["authority"]["allow"]
    )
    effective["validation"]["required_commands"] = _ordered_union(
        approved["validation"]["required_commands"], current["validation"]["required_commands"]
    )
    effective["acceptance"]["evidence"] = _ordered_union(
        approved["acceptance"]["evidence"], current["acceptance"]["evidence"]
    )
    effective["ticket"]["allowed_states"] = _ordered_intersection(
        approved["ticket"]["allowed_states"], current["ticket"]["allowed_states"]
    )
    effective["ticket"]["material_fields"] = _ordered_union(
        approved["ticket"]["material_fields"], current["ticket"]["material_fields"]
    )
    effective["ticket"]["require_no_blockers"] = (
        approved["ticket"]["require_no_blockers"] or current["ticket"]["require_no_blockers"]
    )
    return effective


def _require_policy_identity(
    policy: Mapping[str, Any],
    current: _CurrentPolicy,
    *,
    project: Mapping[str, Any],
    work: Mapping[str, Any],
    mailbox_remote: str,
    mailbox_branch: str,
    mailbox_realm: str,
    approval: Mapping[str, Any],
) -> None:
    expected_repository = project["repository"]
    if current.repository != expected_repository:
        raise MailboxTransitionRejected("current policy repository does not match the project")
    if project["policy"] != {"repository": current.repository, "path": current.path}:
        raise MailboxTransitionRejected("project policy locator contradicts the current target")
    if approval["policy"]["repository"] != current.repository:
        raise MailboxTransitionRejected("approval policy repository does not match the project")
    if approval["policy"]["path"] != current.path:
        raise MailboxTransitionRejected("approval policy path does not match the current target")
    if policy["mailbox"] != {
        "remote": mailbox_remote,
        "realm_id": mailbox_realm,
        "canonical_branch": mailbox_branch,
        "project_id": work["project_id"],
    }:
        raise MailboxTransitionRejected("project policy mailbox identity is incompatible")
    if policy["repository"]["identity"] != expected_repository:
        raise MailboxTransitionRejected("project policy repository identity is incompatible")
    if policy["execution"] != {
        "capability": "agent-scripts.implement-ticket/delegated-execution/v2",
        "delivery_outcome": "ready_pr",
        "parallel_assignments": False,
    }:
        raise MailboxTransitionRejected("project policy execution boundary is unsupported")


def _read_policy_at_commit(target: PolicyTarget, commit: str) -> dict[str, Any]:
    _require_sha(commit, "approved policy commit")
    fetched = run_git(target.checkout, ("fetch", "--no-tags", target.remote, commit))
    _require_git(fetched, "fetch approved project-policy commit")
    content = _git_output(
        target.checkout,
        ("show", f"{commit}:{target.path}"),
        "read approved project policy",
    )
    with tempfile.TemporaryDirectory(prefix="atelier-approved-policy-") as temporary:
        policy_path = Path(temporary) / "policy.yaml"
        policy_path.write_text(content, encoding="utf-8")
        return validate_project_policy(policy_path)


def _policy_remote_matches_repository(target: PolicyTarget, repository: str) -> bool:
    configured = run_git(
        target.checkout,
        ("remote", "get-url", "--all", target.remote),
    )
    if configured.returncode == 0:
        urls = [line.strip() for line in configured.stdout.splitlines() if line.strip()]
        if len(urls) != 1:
            return False
        remote_url = urls[0]
    else:
        remote_url = target.remote
    return _github_remote_url(remote_url, repository=repository)


def _candidate_remote_reachable(candidate: Mapping[str, Any]) -> bool:
    remote_url = candidate.get("remote_url")
    remote_ref = candidate.get("remote_ref")
    head = candidate.get("head_revision")
    if (
        not isinstance(remote_url, str)
        or not remote_url
        or remote_url.startswith("-")
        or not isinstance(remote_ref, str)
        or not remote_ref.startswith("refs/heads/")
        or not isinstance(head, str)
        or SHA_PATTERN.fullmatch(head) is None
    ):
        return False
    with tempfile.TemporaryDirectory(prefix="atelier-candidate-reachability-") as temporary:
        repository = Path(temporary) / "candidate.git"
        initialized = run_git(None, ("init", "--bare", str(repository)))
        if initialized.returncode != 0:
            return False
        fetched = run_git(
            repository,
            (
                "fetch",
                "--no-tags",
                remote_url,
                f"{remote_ref}:refs/atelier/candidate",
            ),
        )
        if fetched.returncode != 0:
            return False
        exists = run_git(repository, ("cat-file", "-e", f"{head}^{{commit}}"))
        if exists.returncode != 0:
            return False
        reachable = run_git(
            repository,
            ("merge-base", "--is-ancestor", head, "refs/atelier/candidate"),
        )
        return reachable.returncode == 0


def _capability_compatible(target: HostTarget) -> bool:
    try:
        result = check_host(
            descriptor_path=target.descriptor_path,
            skill_name=target.skill_name,
            skill_root=target.skill_root,
            connector=target.connector,
            operations=list(target.operations),
        )
    except HostBoundaryError:
        return False
    return (
        result["status"] == "compatible"
        and result["delegated_capability"]
        == "agent-scripts.implement-ticket/delegated-execution/v2"
    )


def _require_fence(work: Mapping[str, Any], fence: ClaimFence) -> dict[str, Any]:
    _require_identifier(fence.claim_id, "clm")
    _require_identifier(fence.worker_run_id, "run")
    if type(fence.sequence) is not int or fence.sequence < 0:
        raise ClaimingError("claim fence sequence must be a nonnegative integer")
    _require_token(fence.continuation_token, "claim fence continuation_token")
    claim = work["claim"]
    if claim is None:
        raise MailboxTransitionRejected(f"{work['id']}: no current claim")
    checkpoint = claim["checkpoint"]
    expected = (
        claim["id"],
        claim["worker_run_id"],
        checkpoint["sequence"],
        checkpoint["continuation_token"],
    )
    supplied = (
        fence.claim_id,
        fence.worker_run_id,
        fence.sequence,
        fence.continuation_token,
    )
    if supplied != expected:
        raise MailboxTransitionRejected(f"{work['id']}: stale or foreign claim fence")
    return copy.deepcopy(claim)


def _validate_checkpoint_request(request: CheckpointRequest) -> None:
    if request.phase not in {"pre_external_mutation", "candidate_published"}:
        raise ClaimingError(f"unsupported checkpoint phase {request.phase!r}")
    if request.action not in AUTHORITY_ACTIONS:
        raise ClaimingError(f"unsupported checkpoint action {request.action!r}")
    if (
        not isinstance(request.proposed_effect_digest, str)
        or DIGEST_PATTERN.fullmatch(request.proposed_effect_digest) is None
    ):
        raise ClaimingError("proposed_effect_digest must be a lowercase SHA-256 digest")
    for label, value in (
        ("candidate_head", request.candidate_head),
        ("acknowledged_candidate_head", request.acknowledged_candidate_head),
    ):
        if value is not None:
            _require_sha(value, label)
    if (request.candidate_head is None) != (request.candidate_remote_ref is None):
        raise ClaimingError("candidate_head and candidate_remote_ref must be present together")
    if request.candidate_remote_ref is not None and not _valid_branch_ref(
        request.candidate_remote_ref
    ):
        raise ClaimingError("candidate_remote_ref must be a valid full Git branch ref")
    _require_token(request.next_continuation_token, "next_continuation_token")
    if request.next_continuation_token == request.fence.continuation_token:
        raise ClaimingError("next continuation token must rotate")
    _require_timestamp(request.recorded_at, "recorded_at")


def _attempt_receipt(
    work: Mapping[str, Any],
    claim: Mapping[str, Any],
    *,
    receipt_id: str,
    outcome: str,
    mutation_ownership: str,
    ended_at: datetime,
    evidence: AttemptEvidence,
) -> dict[str, Any]:
    candidate = copy.deepcopy(claim["candidate"])
    return {
        "schema": "atelier.receipt/v1",
        "id": receipt_id,
        "work_id": work["id"],
        "outcome": outcome,
        "approved_revision": work["revision"],
        "approved_commit": claim["approved_commit"],
        "policy_commit": claim["policy_commit"],
        "claim_id": claim["id"],
        "worker_run_id": claim["worker_run_id"],
        "candidate": candidate,
        "handoff": "transferable" if candidate is not None else "none",
        "native_ticket": {
            "provider": work["native_ticket"]["provider"],
            "id": work["native_ticket"]["id"],
        },
        "validation": [copy.deepcopy(dict(item)) for item in evidence.validation],
        "reviews": [copy.deepcopy(dict(item)) for item in evidence.reviews],
        "unresolved_obligations": list(evidence.unresolved_obligations),
        "mutation_ownership": mutation_ownership,
        "ended_at": _timestamp(ended_at),
    }


def _approved_contract(work: Mapping[str, Any], body: str) -> tuple[Any, ...]:
    return (
        work["schema"],
        work["id"],
        work["title"],
        work["project_id"],
        work["initiative_id"],
        work["revision"],
        tuple(work["dependencies"]),
        tuple(work["replaces"]),
        copy.deepcopy(work["native_ticket"]),
        copy.deepcopy(work["approval"]),
        body,
    )


def _read_work(root: Path, work_id: str) -> tuple[dict[str, Any], str]:
    path = root / _work_path(work_id)
    work, body = _read_document(path)
    if work["id"] != work_id:
        raise ClaimingError(f"{work_id}: work document identity mismatch")
    return work, body


def _read_work_at(root: Path, revision: str, path: str) -> tuple[dict[str, Any], str]:
    result = run_git(root, ("show", f"{revision}:{path}"))
    if result.returncode != 0:
        raise ClaimingError(f"{path}@{revision}: approved work is unreadable")
    with tempfile.TemporaryDirectory(prefix="atelier-approved-work-") as temporary:
        document_path = Path(temporary) / "work.md"
        document_path.write_text(result.stdout, encoding="utf-8")
        return _read_document(document_path)


def _claim_result(
    result: WriteResult,
    work_id: str,
    status: str,
    claim: Mapping[str, Any] | None,
) -> ClaimResult:
    checkpoint = claim["checkpoint"] if claim is not None else None
    return ClaimResult(
        operation=result.operation,
        work_id=work_id,
        status=status,
        claim_id=claim["id"] if claim is not None else None,
        worker_run_id=claim["worker_run_id"] if claim is not None else None,
        sequence=checkpoint["sequence"] if checkpoint is not None else None,
        continuation_token=checkpoint["continuation_token"] if checkpoint is not None else None,
        commit=result.commit,
        base_revision=result.base_revision,
        branch=result.branch,
        attempts=result.attempts,
        recovered=result.recovered,
    )


def _at(value: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = value
    for part in path:
        current = current[part]
    return current


def _ordered_union(first: Sequence[str], second: Sequence[str]) -> list[str]:
    return list(dict.fromkeys((*first, *second)))


def _ordered_intersection(first: Sequence[str], second: Sequence[str]) -> list[str]:
    allowed = set(second)
    return [item for item in first if item in allowed]


def _require_identifier(value: str, prefix: str) -> None:
    if not isinstance(value, str):
        raise ClaimingError(f"{prefix} identifier must be a string")
    match = ID_PATTERN.fullmatch(value)
    if match is None or match.group("prefix") != prefix:
        raise ClaimingError(f"invalid {prefix} identifier: {value!r}")


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise ClaimingError(f"{label} must be a lowercase 40-character Git SHA")


def _require_token(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ClaimingError(f"{label} must be nonempty")


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ClaimingError(f"{label} must be nonempty")


def _require_timestamp(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ClaimingError(f"{label} must be a timezone-aware datetime")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _work_path(work_id: str) -> str:
    return f"work/{work_id}/work.md"


def _message_path(work_id: str, message_id: str) -> str:
    return f"work/{work_id}/messages/{message_id}.md"


def _receipt_path(work_id: str, receipt_id: str) -> str:
    return f"work/{work_id}/receipts/{receipt_id}.md"


def _read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClaimingError(f"request is unreadable: {error}") from error
    if not isinstance(value, dict):
        raise ClaimingError("request must be a JSON object")
    return value


def _coordinator(value: Mapping[str, Any]) -> ClaimCoordinator:
    mailbox = value["mailbox"]
    return ClaimCoordinator(
        mailbox["remote"],
        mailbox["canonical_branch"],
        max_attempts=mailbox.get("max_attempts", 3),
    )


def _policy_target(value: Mapping[str, Any]) -> PolicyTarget:
    return PolicyTarget(
        checkout=Path(value["checkout"]),
        remote=value["remote"],
        canonical_ref=value["canonical_ref"],
        path=value["path"],
    )


def _host_target(value: Mapping[str, Any]) -> HostTarget:
    return HostTarget(
        descriptor_path=Path(value["descriptor_path"]),
        skill_name=value["skill_name"],
        skill_root=Path(value["skill_root"]),
        connector=value["connector"],
        operations=tuple(value["operations"]),
    )


def _fence(value: Mapping[str, Any]) -> ClaimFence:
    return ClaimFence(
        claim_id=value["claim_id"],
        worker_run_id=value["worker_run_id"],
        sequence=value["sequence"],
        continuation_token=value["continuation_token"],
    )


def _evidence(value: Mapping[str, Any] | None) -> AttemptEvidence:
    supplied = value or {}
    return AttemptEvidence(
        validation=tuple(supplied.get("validation", ())),
        reviews=tuple(supplied.get("reviews", ())),
        unresolved_obligations=tuple(supplied.get("unresolved_obligations", ())),
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ClaimingError("timestamp must be an ISO 8601 date-time") from error
    _require_timestamp(parsed, "timestamp")
    return parsed


def _execution_arguments(
    request: Mapping[str, Any],
) -> tuple[PolicyTarget, Path, datetime, datetime | None]:
    observation = request["observation"]
    now = _parse_timestamp(request["now"]) if request.get("now") is not None else None
    return (
        _policy_target(request["policy"]),
        Path(observation["path"]),
        _parse_timestamp(observation["not_before"]),
        now,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    identifier = commands.add_parser("new-id", help="generate a strict Atelier identifier")
    identifier.add_argument("prefix", choices=("clm", "msg", "rcp", "run"))
    for name in ("claim", "checkpoint", "block", "release", "takeover"):
        command = commands.add_parser(name)
        command.add_argument("request", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "new-id":
        print(new_identifier(args.prefix))
        return 0
    try:
        request = _read_request(args.request)
        coordinator = _coordinator(request)
        if args.command == "claim":
            policy, observation, not_before, now = _execution_arguments(request)
            result = coordinator.claim(
                request["work_id"],
                claim_id=request["claim_id"],
                worker_run_id=request["worker_run_id"],
                continuation_token=request["continuation_token"],
                approved_commit=request["approved_commit"],
                claimed_at=_parse_timestamp(request["claimed_at"]),
                policy_target=policy,
                host_target=_host_target(request["host"]),
                observation_path=observation,
                observation_not_before=not_before,
                now=now,
            )
        elif args.command == "checkpoint":
            policy, observation, not_before, now = _execution_arguments(request)
            checkpoint = request["checkpoint"]
            result = coordinator.authorize(
                request["work_id"],
                CheckpointRequest(
                    fence=_fence(checkpoint["fence"]),
                    phase=checkpoint["phase"],
                    action=checkpoint["action"],
                    proposed_effect_digest=checkpoint["proposed_effect_digest"],
                    candidate_head=checkpoint["candidate_head"],
                    candidate_remote_ref=checkpoint["candidate_remote_ref"],
                    acknowledged_candidate_head=checkpoint["acknowledged_candidate_head"],
                    next_continuation_token=checkpoint["next_continuation_token"],
                    recorded_at=_parse_timestamp(checkpoint["recorded_at"]),
                    candidate=checkpoint["candidate"],
                ),
                approved_commit=request["approved_commit"],
                policy_target=policy,
                host_target=_host_target(request["host"]),
                observation_path=observation,
                observation_not_before=not_before,
                now=now,
            )
        elif args.command == "block":
            result = coordinator.block(
                request["work_id"],
                _fence(request["fence"]),
                message_id=request["message_id"],
                receipt_id=request["receipt_id"],
                subject=request["subject"],
                detail=request["detail"],
                created_at=_parse_timestamp(request["created_at"]),
                evidence=_evidence(request.get("evidence")),
            )
        elif args.command == "release":
            result = coordinator.release(
                request["work_id"],
                _fence(request["fence"]),
                receipt_id=request["receipt_id"],
                reason=request["reason"],
                ended_at=_parse_timestamp(request["ended_at"]),
                evidence=_evidence(request.get("evidence")),
            )
        else:
            policy, observation, not_before, now = _execution_arguments(request)
            result = coordinator.takeover(
                request["work_id"],
                _fence(request["replaced_fence"]),
                claim_id=request["claim_id"],
                worker_run_id=request["worker_run_id"],
                continuation_token=request["continuation_token"],
                takeover_message_id=request["takeover_message_id"],
                takeover_receipt_id=request.get("takeover_receipt_id"),
                reason=request["reason"],
                taken_over_at=_parse_timestamp(request["taken_over_at"]),
                approved_commit=request["approved_commit"],
                policy_target=policy,
                host_target=_host_target(request["host"]),
                observation_path=observation,
                observation_not_before=not_before,
                now=now,
            )
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        ClaimingError,
        MailboxTransitionRejected,
        MailboxWriteError,
        MailboxValidationError,
    ) as error:
        print(f"claiming failed: {error}", file=sys.stderr)
        return 1


__all__ = [
    "AttemptEvidence",
    "CheckpointRequest",
    "ClaimCoordinator",
    "ClaimFence",
    "ClaimResult",
    "ClaimingError",
    "HostTarget",
    "PolicyTarget",
    "new_identifier",
]


if __name__ == "__main__":
    raise SystemExit(main())
