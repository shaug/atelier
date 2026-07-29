#!/usr/bin/env python3
"""Prepare, checkpoint, and finalize one delegated Agent Scripts execution."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
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
from skills.atelier.scripts.host_boundary import check_host
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
        checkpoint_command: Sequence[str],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build one exact invocation from fresh approved mailbox and provider state."""

        dependency = self._dependency(host_target)
        if not checkpoint_command or any(not item for item in checkpoint_command):
            raise DelegationError("checkpoint command must contain nonempty arguments")

        def inspect(context: TransitionContext) -> dict[str, Any]:
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
                    for evidence in state.work["approval"]["acceptance"]["required_evidence"]
                ],
                "starting_deployment": None,
                "checkpoint": {
                    "command": list(checkpoint_command),
                    "last_sequence": claim["checkpoint"]["sequence"],
                    "continuation_token": claim["checkpoint"]["continuation_token"],
                },
            }
            _require_valid(dependency, "invocation", invocation)
            return invocation

        return self.claims.writer.observe("prepare delegation", inspect)

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
        candidate = (
            _mailbox_candidate(request.get("candidate"), recorded_at)
            if request["phase"] == "candidate_published"
            else None
        )
        try:
            result = self.claims.authorize(
                work_id,
                CheckpointRequest(
                    fence=ClaimFence(
                        claim_id=current_claim["id"],
                        worker_run_id=invocation["invocation_id"],
                        sequence=current_claim["checkpoint"]["sequence"],
                        continuation_token=prior_token,
                    ),
                    phase=request["phase"],
                    action=request["action"],
                    proposed_effect_digest=_digest(request["proposed_effect"]),
                    candidate_head=request["candidate"]["head_sha"]
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
            if state.work["status"] != "active":
                raise MailboxTransitionRejected(f"{work_id}: terminal result requires active work")
            claim = copy.deepcopy(_require_fence(state.work, fence))
            if result["ticket"]["observation"] != state.ticket_digest:
                raise MailboxTransitionRejected("terminal ticket observation is not current")
            evidence = _attempt_evidence(result)
            outcome = "delivered" if terminal == "ready_pr" else "blocked"
            body = (
                "Delegated candidate delivered."
                if outcome == "delivered"
                else result["blocking_reason"]
            )
            if outcome == "delivered":
                self.claims._verify_candidate(claim["candidate"])
                _require_ready_pr(result, state.observation, claim)
                claim["candidate"] = _delivered_candidate(result, claim["candidate"])
            else:
                _require_blocked_result(result, claim)
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
                "mechanism": item["name"],
                "verdict": "clean" if item["outcome"] == "passed" else item["outcome"],
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
        live["head"]["ref"],
        live["head"]["sha"],
        live["base"]["ref"],
        live["base"]["sha"],
    ) != (
        pull_request["url"],
        "OPEN",
        False,
        "MERGEABLE",
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


def _require_blocked_result(result: Mapping[str, Any], claim: Mapping[str, Any]) -> None:
    if not result["blocking_reason"] or not result["unresolved_obligations"]:
        raise MailboxTransitionRejected(
            "blocked results require a reason and unresolved obligations"
        )
    candidate = result["candidate"]
    current = claim["candidate"]
    if candidate is None:
        if current is not None:
            raise MailboxTransitionRejected("blocked result omitted an acknowledged candidate")
        return
    if current is None or candidate["head_sha"] != current["head_revision"]:
        raise MailboxTransitionRejected("blocked result candidate does not match the claim")


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
            checkpoint_command=value["checkpoint_command"],
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
        result = execute_request(_read_json(_parser().parse_args().request))
    except (DelegationError, MailboxTransitionRejected, KeyError, TypeError, ValueError) as error:
        print(f"ERROR delegation: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
