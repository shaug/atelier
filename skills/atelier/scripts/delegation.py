#!/usr/bin/env python3
"""Prepare, checkpoint, and finalize one delegated Agent Scripts execution."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import secrets
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills.atelier.scripts.claiming import (
    AUTHORITY_ACTIONS,
    AttemptEvidence,
    CheckpointRequest,
    ClaimCoordinator,
    ClaimFence,
    HostTarget,
    _attempt_receipt,
    _message_path,
    _read_work,
    _receipt_path,
    _timestamp,
    _work_path,
)
from skills.atelier.scripts.git_mailbox import (
    FileChange,
    MailboxTransitionRejected,
    TransitionContext,
    TransitionPlan,
    WriteResult,
)
from skills.atelier.scripts.host_boundary import HostBoundaryError, check_host, validate_observation
from skills.atelier.scripts.identifiers import new_identifier
from skills.atelier.scripts.planning import PolicyTarget, _render_document

CAPABILITY = "agent-scripts.implement-ticket/delegated-execution/v2"
INVOCATION_SCHEMA = "agent-scripts.implement-ticket/delegated-invocation/v2"
REQUEST_SCHEMA = "agent-scripts.implement-ticket/checkpoint-request/v2"
RESPONSE_SCHEMA = "agent-scripts.implement-ticket/checkpoint-response/v2"
RESULT_SCHEMA = "agent-scripts.implement-ticket/delegated-result/v2"
ACCEPTED_TERMINALS = ("ready_pr", "blocked", "requires_epic")
SECTION_PATTERN = re.compile(
    r"^## (?P<title>[^\n]+)\n\n(?P<body>.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)


class DelegationError(RuntimeError):
    """The delegated execution boundary cannot safely continue."""


class DelegationCoordinator:
    """Host-owned adapter around the dependency-owned delegated protocol."""

    def __init__(self, claims: ClaimCoordinator):
        self.claims = claims

    def prepare(
        self,
        work_id: str,
        fence: ClaimFence,
        *,
        approved_commit: str,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        checkpoint_invocation_path: Path,
        observation_command: Sequence[str],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build one exact invocation from fresh approved mailbox and provider state."""

        dependency = self._dependency(host_target)
        if (
            not observation_command
            or any(not isinstance(item, str) or not item for item in observation_command)
        ):
            raise DelegationError("observation command must contain nonempty string arguments")
        checkpoint_command = _checkpoint_command(
            invocation_path=checkpoint_invocation_path,
            mailbox_remote=self.claims.writer.remote,
            mailbox_branch=self.claims.writer.branch,
            work_id=work_id,
            approved_commit=approved_commit,
            policy_target=policy_target,
            host_target=host_target,
            observation_command=observation_command,
        )
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            state = self.claims._execution_state(
                context,
                work_id,
                approved_commit=approved_commit,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )
            if state.work["status"] != "active":
                raise MailboxTransitionRejected(f"{work_id}: delegation requires active work")
            claim = _require_fence(state.work, fence)
            if claim["invocation_digest"] is not None:
                raise MailboxTransitionRejected(
                    f"{work_id}: delegated invocation is already sealed"
                )
            sections = _sections(state.body)
            policy = state.effective_policy
            base_ref = policy["repository"]["canonical_ref"]
            base_sha = state.current_policy.commit
            invocation = {
                "schema": INVOCATION_SCHEMA,
                "capability": CAPABILITY,
                "invocation_id": claim["worker_run_id"],
                "ticket": {
                    "provider": state.work["native_ticket"]["provider"],
                    "id": state.work["native_ticket"]["id"],
                    "url": state.work["native_ticket"]["url"],
                    "observation": state.ticket_digest,
                },
                "repository": {
                    "identity": state.project["repository"],
                    "remote_url": (
                        "https://github.com/"
                        + state.project["repository"].removeprefix("github:")
                        + ".git"
                    ),
                    "base_ref": base_ref,
                    "base_sha": base_sha,
                },
                "work": {
                    "id": work_id,
                    "revision": state.work["revision"],
                    "approval_evidence": approved_commit,
                    "intent": sections["intent"],
                    "scope": [sections["scope"]],
                    "non_goals": [sections["non goals"]],
                    "constraints": [sections["constraints"]],
                    "done_definition": [sections["done definition"]],
                },
                "validation": policy["validation"]["required_commands"],
                "review": {
                    "independent": True,
                    "unresolved_feedback_required": True,
                },
                "authority": {
                    "allow": [
                        action
                        for action in state.work["approval"]["authority_ceiling"]
                        if action in policy["authority"]["allow"] and action in AUTHORITY_ACTIONS
                    ]
                },
                "desired_outcome": "ready_pr",
                "accepted_terminal_states": list(ACCEPTED_TERMINALS),
                "acceptance_requirements": [
                    {
                        "criterion": evidence,
                        "required": True,
                        "evidence_category": evidence,
                        "stage": "pre_merge",
                        "identity": "candidate",
                        "environment": None,
                        "url": None,
                        "source": "atelier.approval.acceptance.required_evidence",
                    }
                    for evidence in policy["acceptance"]["evidence"]
                ],
                "starting_deployment": None,
                "checkpoint": {
                    "command": list(checkpoint_command),
                    "last_sequence": claim["checkpoint"]["sequence"],
                    "continuation_token": claim["checkpoint"]["continuation_token"],
                },
            }
            _require_valid(dependency, "invocation", invocation)
            _write_json_atomic(checkpoint_invocation_path, invocation)
            _probe_checkpoint_command(checkpoint_command)
            updated_claim = copy.deepcopy(claim)
            updated_claim["invocation_digest"] = _canonical_digest(invocation)
            planned.clear()
            planned.update(state=state, claim=updated_claim, invocation=invocation)

        def plan(context: TransitionContext) -> TransitionPlan:
            state = planned["state"]
            work = copy.deepcopy(state.work)
            work["claim"] = planned["claim"]
            return TransitionPlan(
                commit_message=f"seal delegated invocation for {work_id}",
                changes=(FileChange(_work_path(work_id), _render_document(work, state.body)),),
            )

        self.claims.writer.publish("prepare delegation", revalidate=revalidate, plan=plan)
        return copy.deepcopy(planned["invocation"])

    def checkpoint(
        self,
        work_id: str,
        invocation: Mapping[str, Any],
        request: Mapping[str, Any],
        *,
        approved_commit: str,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        recorded_at: datetime,
        next_continuation_token: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Service one request, denying drift without consuming the claim fence."""

        dependency = self._dependency(host_target)
        _require_valid(dependency, "invocation", invocation)
        _require_valid(dependency, "checkpoint-request", request)
        if request["invocation_id"] != invocation["invocation_id"]:
            raise DelegationError("checkpoint invocation identity mismatch")
        if request["capability"] != CAPABILITY:
            raise DelegationError("checkpoint capability mismatch")
        current_claim = self.claims.writer.observe(
            "read delegated checkpoint fence",
            lambda context: copy.deepcopy(_read_work(context.checkout, work_id)[0]["claim"]),
        )
        if current_claim is None or current_claim["worker_run_id"] != invocation["invocation_id"]:
            raise DelegationError("delegated invocation no longer owns the current claim")
        prior_token = request["continuation_token"]
        response = {
            "schema": RESPONSE_SCHEMA,
            "invocation_id": request["invocation_id"],
            "request_sequence": request["sequence"],
            "prior_continuation_token": prior_token,
            "continuation_token": prior_token,
            "decision": "deny",
            "reason": None,
            "acknowledged_candidate_sha": None,
            "observed_deployment": None,
        }
        try:
            if current_claim["invocation_digest"] != _canonical_digest(invocation):
                raise MailboxTransitionRejected(
                    "delegated invocation does not match its sealed digest"
                )
            if request["sequence"] != current_claim["checkpoint"]["sequence"] + 1:
                raise MailboxTransitionRejected("checkpoint sequence does not advance exactly once")
            if prior_token != current_claim["checkpoint"]["continuation_token"]:
                raise MailboxTransitionRejected("checkpoint continuation token is stale")
            _require_checkpoint_candidate(invocation, request.get("candidate"))
            candidate = (
                _mailbox_candidate(request.get("candidate"), recorded_at)
                if request["phase"] == "candidate_published"
                else None
            )
            result = self.claims.authorize(
                work_id,
                CheckpointRequest(
                    fence=ClaimFence(
                        claim_id=current_claim["id"],
                        worker_run_id=invocation["invocation_id"],
                        sequence=request["sequence"] - 1,
                        continuation_token=prior_token,
                    ),
                    phase=request["phase"],
                    action=request["action"],
                    proposed_effect_digest=_digest(request["proposed_effect"]),
                    candidate_head=request["candidate"]["head_sha"]
                    if request["candidate"]
                    else None,
                    candidate_remote_ref=request["candidate"]["remote_ref"]
                    if request["candidate"]
                    else None,
                    acknowledged_candidate_head=(
                        request["candidate"]["head_sha"]
                        if request["phase"] == "candidate_published" and request["candidate"]
                        else None
                    ),
                    next_continuation_token=next_continuation_token,
                    recorded_at=recorded_at,
                    candidate=candidate,
                    ticket_observation_digest=request["ticket_observation"],
                ),
                approved_commit=approved_commit,
                policy_target=policy_target,
                host_target=host_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
                state_revalidator=lambda state: _require_current_invocation_contract(
                    invocation, state
                ),
            )
        except (DelegationError, MailboxTransitionRejected) as error:
            response["reason"] = str(error)
        else:
            response.update(
                decision="allow",
                reason=None,
                continuation_token=result.continuation_token,
                acknowledged_candidate_sha=(
                    request["candidate"]["head_sha"]
                    if request["phase"] == "candidate_published" and request["candidate"]
                    else None
                ),
            )
        if response["decision"] == "allow":
            errors = dependency.validate_checkpoint_progress(
                current_claim["checkpoint"]["sequence"],
                current_claim["checkpoint"]["continuation_token"],
                dict(request),
                response,
            )
        else:
            errors = dependency.validate_checkpoint_exchange(dict(request), response)
        if errors:
            raise DelegationError("; ".join(errors))
        return response

    def finalize(
        self,
        work_id: str,
        invocation: Mapping[str, Any],
        result: Mapping[str, Any],
        fence: ClaimFence,
        *,
        approved_commit: str,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        ended_at: datetime,
        now: datetime | None = None,
    ) -> WriteResult:
        """Validate one terminal result and record one immutable attempt receipt."""

        dependency = self._dependency(host_target)
        _require_valid(dependency, "invocation", invocation)
        current_claim = self.claims.writer.observe(
            "read delegated result fence",
            lambda context: copy.deepcopy(_read_work(context.checkout, work_id)[0]["claim"]),
        )
        if current_claim is None or (
            current_claim["id"],
            current_claim["worker_run_id"],
            current_claim["checkpoint"]["sequence"],
            current_claim["checkpoint"]["continuation_token"],
        ) != (
            fence.claim_id,
            fence.worker_run_id,
            fence.sequence,
            fence.continuation_token,
        ):
            raise DelegationError("delegated terminal result claim fence is stale")
        if current_claim["invocation_digest"] != _canonical_digest(invocation):
            raise DelegationError("delegated invocation does not match its sealed digest")
        consumed = list(
            dict.fromkeys(
                entry["action"]
                for entry in current_claim["checkpoint"]["authorizations"]
                if entry["phase"] == "pre_external_mutation"
            )
        )
        errors = dependency.validate_result_checkpoint_state(
            dict(invocation),
            dict(result),
            fence.sequence,
            fence.continuation_token,
            None,
            None,
            consumed,
        )
        if set(result.get("authority_used", [])) != set(consumed):
            errors.append("$.authority_used: does not match Atelier's checkpoint ledger")
        if errors:
            raise DelegationError("; ".join(errors))
        terminal = result["terminal_state"]
        if terminal not in ACCEPTED_TERMINALS:
            raise DelegationError(
                f"terminal state {terminal!r} exceeds Atelier's accepted boundary"
            )
        receipt_id = new_identifier("rcp")
        message_id = new_identifier("msg") if terminal != "ready_pr" else None
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            self.claims._verify_capability(host_target)
            state = self.claims._execution_state(
                context,
                work_id,
                approved_commit=approved_commit,
                policy_target=policy_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                now=now,
            )
            _require_current_invocation_contract(invocation, state)
            if state.work["status"] != "active":
                raise MailboxTransitionRejected(f"{work_id}: terminal result requires active work")
            claim = copy.deepcopy(_require_fence(state.work, fence))
            if claim["invocation_digest"] != _canonical_digest(invocation):
                raise MailboxTransitionRejected(
                    "delegated invocation does not match its sealed digest"
                )
            if result["ticket"]["observation"] != state.ticket_digest:
                raise MailboxTransitionRejected("terminal ticket observation is not current")
            _require_tracker_transition(result, state.observation)
            evidence = _attempt_evidence(result)
            outcome = "delivered" if terminal == "ready_pr" else "blocked"
            body = (
                "Delegated candidate delivered."
                if outcome == "delivered"
                else (
                    result["blocking_reason"]
                    if terminal == "blocked"
                    else result["handoff"]["reason"] or result["next_action"]
                )
            )
            if outcome == "delivered":
                self.claims._verify_candidate(claim["candidate"])
                _require_ready_pr(result, state.observation, claim)
                claim["candidate"] = _delivered_candidate(result, claim["candidate"])
            else:
                blocked_candidate = _blocked_candidate(result, claim, ended_at)
                if blocked_candidate is not None:
                    self.claims._verify_candidate(blocked_candidate)
                    claim["candidate"] = blocked_candidate
            message = None
            if outcome == "blocked":
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
                    "created_at": _timestamp(ended_at),
                    "subject": (
                        "Delegated work requires epic planning"
                        if terminal == "requires_epic"
                        else "Delegated work is blocked"
                    ),
                }
            work_for_receipt = copy.deepcopy(state.work)
            work_for_receipt["claim"] = claim
            receipt = _attempt_receipt(
                work_for_receipt,
                claim,
                receipt_id=receipt_id,
                outcome=outcome,
                mutation_ownership="retained",
                ended_at=ended_at,
                evidence=evidence,
            )
            planned.clear()
            planned.update(
                state=state,
                claim=claim,
                receipt=receipt,
                outcome=outcome,
                body=body,
                message=message,
            )

        def plan(context: TransitionContext) -> TransitionPlan:
            state = planned["state"]
            work = copy.deepcopy(state.work)
            work["claim"] = planned["claim"]
            work["status"] = planned["outcome"]
            work["attempt_receipt_id"] = receipt_id
            if planned["outcome"] == "delivered":
                work["delivery_receipt_id"] = receipt_id
            else:
                work["blocking_message_id"] = message_id
            changes = [
                FileChange(
                    _receipt_path(work_id, receipt_id),
                    _render_document(planned["receipt"], planned["body"]),
                ),
                FileChange(_work_path(work_id), _render_document(work, state.body)),
            ]
            if planned["message"] is not None:
                changes.insert(
                    0,
                    FileChange(
                        _message_path(work_id, message_id),
                        _render_document(planned["message"], planned["body"]),
                    ),
                )
            return TransitionPlan(
                commit_message=f"record delegated {planned['outcome']} result for {work_id}",
                changes=tuple(changes),
            )

        return self.claims.writer.publish("finalize delegation", revalidate=revalidate, plan=plan)

    def _dependency(self, target: HostTarget) -> ModuleType:
        check_host(
            descriptor_path=target.descriptor_path,
            skill_name=target.skill_name,
            skill_root=target.skill_root,
            connector=target.connector,
            operations=list(target.operations),
        )
        path = target.skill_root / "references" / "delegated-execution" / "validate.py"
        spec = importlib.util.spec_from_file_location("_atelier_delegated_validator", path)
        if spec is None or spec.loader is None:
            raise DelegationError("dependency-owned delegated validator cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _require_fence(work: Mapping[str, Any], fence: ClaimFence) -> dict[str, Any]:
    claim = work["claim"]
    if claim is None or (
        claim["id"],
        claim["worker_run_id"],
        claim["checkpoint"]["sequence"],
        claim["checkpoint"]["continuation_token"],
    ) != (
        fence.claim_id,
        fence.worker_run_id,
        fence.sequence,
        fence.continuation_token,
    ):
        raise MailboxTransitionRejected(f"{work['id']}: delegated claim fence is stale")
    return claim


def _sections(body: str) -> dict[str, str]:
    sections = {
        match.group("title").strip().lower(): match.group("body").strip()
        for match in SECTION_PATTERN.finditer(body)
    }
    required = {"intent", "scope", "non goals", "constraints", "done definition"}
    missing = sorted(required - sections.keys())
    if missing or any(not sections[name] for name in required):
        raise DelegationError("approved work body is missing sections: " + ", ".join(missing))
    return sections


def _require_valid(dependency: ModuleType, kind: str, value: Mapping[str, Any]) -> None:
    errors = dependency.validate(kind, dict(value))
    if errors:
        raise DelegationError("; ".join(errors))


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _digest(encoded)


def _require_checkpoint_candidate(
    invocation: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
) -> None:
    if candidate is None:
        return
    repository = invocation["repository"]
    if (
        candidate["repository"] != repository["identity"]
        or candidate["remote_url"] != repository["remote_url"]
        or candidate["base_sha"] != repository["base_sha"]
    ):
        raise MailboxTransitionRejected("checkpoint candidate is foreign to the sealed invocation")
    if candidate["remote_ref"] == repository["base_ref"]:
        raise MailboxTransitionRejected(
            "checkpoint candidate cannot publish to the canonical base ref"
        )


def _mailbox_candidate(
    value: Mapping[str, Any] | None, recorded_at: datetime
) -> dict[str, Any] | None:
    if value is None:
        return None
    candidate = {
        "repository": value["repository"],
        "remote": "origin",
        "remote_url": value["remote_url"],
        "remote_ref": value["remote_ref"],
        "base_revision": value["base_sha"],
        "head_revision": value["head_sha"],
        "pull_request": None,
        "workspace_id": None,
        "published_at": _timestamp(recorded_at),
    }
    return candidate


def _attempt_evidence(result: Mapping[str, Any]) -> AttemptEvidence:
    if any(item["name"] != "review-code-change" for item in result["reviews"]):
        raise MailboxTransitionRejected(
            "review evidence uses a mechanism Atelier cannot represent"
        )
    verdicts = {
        "passed": "clean",
        "failed": "changes_required",
        "unavailable": "blocked",
    }
    return AttemptEvidence(
        validation=tuple(
            {
                "command": item["name"],
                "outcome": item["outcome"],
                "candidate_revision": item["candidate_sha"],
                "observed_at": item["observed_at"],
            }
            for item in result["validation"]
        ),
        reviews=tuple(
            {
                "mechanism": "review-code-change",
                "verdict": verdicts[item["outcome"]],
                "candidate_revision": item["candidate_sha"],
                "comparison_base_revision": result["repository"]["base_sha"],
                "observed_at": item["observed_at"],
            }
            for item in result["reviews"]
        ),
        unresolved_obligations=tuple(result["unresolved_obligations"]),
    )


def _require_ready_pr(
    result: Mapping[str, Any],
    observation: Mapping[str, Any],
    claim: Mapping[str, Any],
) -> None:
    candidate = result["candidate"]
    if result["implementation_state"] != "published" or candidate is None:
        raise MailboxTransitionRejected("ready_pr requires one published candidate")
    publication = candidate["publication"]
    if publication["kind"] != "ordinary" or len(publication["pull_requests"]) != 1:
        raise MailboxTransitionRejected("Atelier v0 accepts one ordinary pull request")
    pull_request = publication["pull_requests"][0]
    if (
        pull_request["head_ref"],
        pull_request["head_sha"],
        pull_request["base_sha"],
    ) != (
        candidate["remote_ref"],
        candidate["head_sha"],
        candidate["base_sha"],
    ):
        raise MailboxTransitionRejected(
            "terminal pull request does not identify the acknowledged candidate"
        )
    current = claim["candidate"]
    if current is None or (
        candidate["repository"],
        candidate["remote_url"],
        candidate["remote_ref"],
        candidate["base_sha"],
        candidate["head_sha"],
    ) != (
        current["repository"],
        current["remote_url"],
        current["remote_ref"],
        current["base_revision"],
        current["head_revision"],
    ):
        raise MailboxTransitionRejected(
            "terminal candidate does not match the acknowledged claim candidate"
        )
    live = observation["pull_request"]
    if live is None or (
        live["url"],
        live["state"],
        live["is_draft"],
        live["mergeable"],
        live["head"]["repository"],
        live["head"]["ref"],
        live["head"]["sha"],
        live["base"]["ref"],
        live["base"]["sha"],
    ) != (
        pull_request["url"],
        "OPEN",
        False,
        "MERGEABLE",
        candidate["repository"].removeprefix("github:"),
        pull_request["head_ref"],
        pull_request["head_sha"],
        pull_request["base_ref"],
        pull_request["base_sha"],
    ):
        raise MailboxTransitionRejected("live pull request identity is not the terminal candidate")
    if any(
        check["status"].upper() != "COMPLETED"
        or (check["conclusion"] or "").upper() not in {"SUCCESS", "NEUTRAL", "SKIPPED"}
        for check in observation["checks"]
    ):
        raise MailboxTransitionRejected("live candidate checks are incomplete or failing")
    if any(
        not thread["is_resolved"] and not thread["is_outdated"] for thread in observation["threads"]
    ):
        raise MailboxTransitionRejected("live pull request has unresolved review threads")
    feedback = result["feedback"]
    if feedback is None or feedback["unresolved_material_count"] != 0:
        raise MailboxTransitionRejected("ready_pr requires zero unresolved material feedback")
    if any(
        item["outcome"] != "passed" or item["candidate_sha"] != candidate["head_sha"]
        for item in result["validation"]
    ):
        raise MailboxTransitionRejected("validation evidence is not passing on the candidate")
    if not result["reviews"] or any(
        item["outcome"] != "passed" or item["candidate_sha"] != candidate["head_sha"]
        for item in result["reviews"]
    ):
        raise MailboxTransitionRejected("independent review evidence is not clean on the candidate")
    required = [item for item in result["acceptance_evidence"] if item["required"]]
    if any(
        item["status"] != "pass" or item["candidate_sha"] != candidate["head_sha"]
        for item in required
    ):
        raise MailboxTransitionRejected(
            "required acceptance evidence is not candidate-bound and passing"
        )


def _delivered_candidate(
    result: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    value = copy.deepcopy(current)
    value["pull_request"] = result["candidate"]["publication"]["pull_requests"][0]["url"]
    return value


def _blocked_candidate(
    result: Mapping[str, Any], claim: Mapping[str, Any], recorded_at: datetime
) -> dict[str, Any] | None:
    if result["terminal_state"] == "requires_epic":
        return copy.deepcopy(claim["candidate"])
    candidate = result["candidate"]
    current = claim["candidate"]
    if candidate is None:
        if current is not None:
            raise MailboxTransitionRejected("blocked result omitted an acknowledged candidate")
        return None
    candidate_identity = (
        candidate["repository"],
        candidate["remote_url"],
        candidate["remote_ref"],
        candidate["base_sha"],
        candidate["head_sha"],
    )
    if current is not None and candidate_identity == (
        current["repository"],
        current["remote_url"],
        current["remote_ref"],
        current["base_revision"],
        current["head_revision"],
    ):
        return copy.deepcopy(current)
    ledger = claim["checkpoint"]["authorizations"]
    if (
        result["implementation_state"] != "published"
        or not ledger
        or ledger[-1]["phase"] != "pre_external_mutation"
        or ledger[-1]["action"] != "repository.candidate.push"
        or ledger[-1]["candidate_head"] != candidate["head_sha"]
        or ledger[-1]["candidate_remote_ref"] != candidate["remote_ref"]
    ):
        raise MailboxTransitionRejected(
            "blocked published candidate lacks its exact push authorization"
        )
    return _mailbox_candidate(candidate, recorded_at)


def _require_tracker_transition(result: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
    transition = result["tracker_transition"]
    issue = observation["issue"]
    expected = (
        result["ticket"]["provider"],
        str(issue["number"]),
        "none",
        issue["state"].lower(),
    )
    actual = (
        transition["provider"],
        str(transition["ticket_id"]),
        transition["mode"],
        transition["state"].lower(),
    )
    if actual != expected or expected[3] != "open":
        raise MailboxTransitionRejected(
            "delegated result tracker transition does not match the current open ticket"
        )


def _require_current_invocation_contract(
    invocation: Mapping[str, Any], state: Any
) -> None:
    policy = state.effective_policy
    current_acceptance = list(policy["acceptance"]["evidence"])
    invocation_acceptance = [
        item["criterion"] for item in invocation["acceptance_requirements"]
    ]
    if invocation["repository"]["identity"] != state.project["repository"]:
        raise MailboxTransitionRejected(
            "delegated invocation repository does not match the current project"
        )
    if invocation["repository"]["base_sha"] != state.current_policy.commit:
        raise MailboxTransitionRejected(
            "delegated invocation base is stale against the current repository"
        )
    if list(invocation["validation"]) != list(policy["validation"]["required_commands"]):
        raise MailboxTransitionRejected(
            "delegated invocation validation does not match current policy"
        )
    if invocation_acceptance != current_acceptance:
        raise MailboxTransitionRejected(
            "delegated invocation acceptance does not match current policy"
        )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DelegationError(f"{path}: expected a JSON object")
    return value


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise DelegationError("timestamps must include a UTC offset")
    return parsed


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


def _policy_target_value(target: PolicyTarget) -> dict[str, Any]:
    return {
        "checkout": str(target.checkout.resolve()),
        "remote": target.remote,
        "canonical_ref": target.canonical_ref,
        "path": target.path,
    }


def _host_target_value(target: HostTarget) -> dict[str, Any]:
    return {
        "descriptor_path": str(target.descriptor_path.resolve()),
        "skill_name": target.skill_name,
        "skill_root": str(target.skill_root.resolve()),
        "connector": target.connector,
        "operations": list(target.operations),
    }


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _checkpoint_command(
    *,
    invocation_path: Path,
    mailbox_remote: str,
    mailbox_branch: str,
    work_id: str,
    approved_commit: str,
    policy_target: PolicyTarget,
    host_target: HostTarget,
    observation_command: Sequence[str],
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "checkpoint-stdio",
        "--invocation",
        str(invocation_path.resolve()),
        "--mailbox-remote",
        mailbox_remote,
        "--mailbox-branch",
        mailbox_branch,
        "--work-id",
        work_id,
        "--approved-commit",
        approved_commit,
        "--policy-target",
        _compact_json(_policy_target_value(policy_target)),
        "--host-target",
        _compact_json(_host_target_value(host_target)),
        "--observation-command",
        _compact_json(list(observation_command)),
    ]


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _probe_checkpoint_command(command: Sequence[str]) -> None:
    completed = subprocess.run(
        [*command, "--probe"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise DelegationError(f"checkpoint command probe failed: {detail}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DelegationError("checkpoint command probe returned malformed JSON") from error
    if response != {"status": "ready"}:
        raise DelegationError("checkpoint command probe did not report ready")


def _checkpoint_stdio_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Service one delegated checkpoint request")
    parser.add_argument("--invocation", required=True, type=Path)
    parser.add_argument("--mailbox-remote", required=True)
    parser.add_argument("--mailbox-branch", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--approved-commit", required=True)
    parser.add_argument("--policy-target", required=True)
    parser.add_argument("--host-target", required=True)
    parser.add_argument("--observation-command", required=True)
    parser.add_argument("--probe", action="store_true")
    return parser


def _json_object_argument(value: str, label: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise DelegationError(f"{label} must be a JSON object")
    return parsed


def _json_command_argument(value: str) -> list[str]:
    parsed = json.loads(value)
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(not isinstance(item, str) or not item for item in parsed)
    ):
        raise DelegationError("observation command must be a nonempty JSON string array")
    return parsed


def _checkpoint_stdio(arguments: Sequence[str]) -> dict[str, Any]:
    args = _checkpoint_stdio_parser().parse_args(arguments)
    policy_target = _policy_target(_json_object_argument(args.policy_target, "policy target"))
    host_target = _host_target(_json_object_argument(args.host_target, "host target"))
    observation_command = _json_command_argument(args.observation_command)
    invocation = _read_json(args.invocation)
    expected_command = _checkpoint_command(
        invocation_path=args.invocation,
        mailbox_remote=args.mailbox_remote,
        mailbox_branch=args.mailbox_branch,
        work_id=args.work_id,
        approved_commit=args.approved_commit,
        policy_target=policy_target,
        host_target=host_target,
        observation_command=observation_command,
    )
    if invocation.get("checkpoint", {}).get("command") != expected_command:
        raise DelegationError("checkpoint adapter arguments do not match the sealed invocation")

    read_boundary = datetime.now(UTC)
    completed = subprocess.run(
        observation_command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise DelegationError(f"native observation command failed: {detail}")
    try:
        observation = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DelegationError("native observation command returned malformed JSON") from error
    if not isinstance(observation, dict):
        raise DelegationError("native observation command must return one JSON object")
    observed_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="atelier-checkpoint-observation-") as temporary:
        observation_path = Path(temporary) / "observation.json"
        _write_json_atomic(observation_path, observation)
        validate_observation(
            observation_path,
            not_before=read_boundary,
            now=observed_at,
        )
        if args.probe:
            return {"status": "ready"}
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise DelegationError("checkpoint request must be one JSON object")
        claims = ClaimCoordinator(args.mailbox_remote, args.mailbox_branch)
        response = DelegationCoordinator(claims).checkpoint(
            args.work_id,
            invocation,
            request,
            approved_commit=args.approved_commit,
            policy_target=policy_target,
            host_target=host_target,
            observation_path=observation_path,
            observation_not_before=read_boundary,
            recorded_at=observed_at,
            next_continuation_token=secrets.token_urlsafe(32),
            now=observed_at,
        )
    return response


def execute_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one explicit host-owned delegation operation from a JSON request."""

    claims = ClaimCoordinator(value["mailbox"]["remote"], value["mailbox"]["branch"])
    delegation = DelegationCoordinator(claims)
    common = {
        "approved_commit": value["approved_commit"],
        "policy_target": _policy_target(value["policy_target"]),
        "host_target": _host_target(value["host_target"]),
        "observation_path": Path(value["observation_path"]),
        "observation_not_before": _parse_timestamp(value["observation_not_before"]),
        "now": _parse_timestamp(value["now"]) if value.get("now") else None,
    }
    operation = value["operation"]
    if operation == "prepare":
        return delegation.prepare(
            value["work_id"],
            _fence(value["fence"]),
            checkpoint_invocation_path=Path(value["checkpoint_invocation_path"]),
            observation_command=value["observation_command"],
            **common,
        )
    if operation == "checkpoint":
        return delegation.checkpoint(
            value["work_id"],
            value["invocation"],
            value["checkpoint_request"],
            recorded_at=_parse_timestamp(value["recorded_at"]),
            next_continuation_token=value["next_continuation_token"],
            **common,
        )
    if operation == "finalize":
        result = delegation.finalize(
            value["work_id"],
            value["invocation"],
            value["result"],
            _fence(value["fence"]),
            ended_at=_parse_timestamp(value["ended_at"]),
            **common,
        )
        return asdict(result)
    raise DelegationError(f"unsupported delegation operation: {operation!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "request", type=Path, help="JSON request describing the host-owned operation"
    )
    return parser


def main() -> int:
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "checkpoint-stdio":
            result = _checkpoint_stdio(sys.argv[2:])
            print(json.dumps(result, sort_keys=True))
        else:
            result = execute_request(_read_json(_parser().parse_args().request))
            print(json.dumps(result, indent=2, sort_keys=True))
    except (
        DelegationError,
        HostBoundaryError,
        MailboxTransitionRejected,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"ERROR delegation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
