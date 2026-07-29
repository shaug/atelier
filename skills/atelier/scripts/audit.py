#!/usr/bin/env python3
"""Live delivery audit and explicit operator acceptance for Atelier v0."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from skills.atelier.scripts.claiming import (
    ClaimCoordinator,
    HostTarget,
    _effective_policy,
    _read_policy_at_commit,
    _read_work,
    _read_work_at,
    _require_policy_identity,
    _timestamp,
    _work_path,
)
from skills.atelier.scripts.git_mailbox import (
    FileChange,
    MailboxTransitionRejected,
    TransitionContext,
    TransitionPlan,
    WriteResult,
    run_git,
)
from skills.atelier.scripts.mailbox import _read_yaml
from skills.atelier.scripts.planning import (
    PlanningError,
    PolicyTarget,
    _read_current_policy,
    _read_project,
    _render_document,
    _ticket_material_digest,
    _validated_observation,
)

EVIDENCE_NAMES = (
    "candidate-remote-reachable",
    "pull-request-head-current",
    "pull-request-open",
    "pull-request-mergeable",
    "required-checks-pass",
    "required-validation-reported",
    "independent-review-current",
    "unresolved-feedback-zero",
)


class AuditError(RuntimeError):
    """The delivery promise cannot be audited without guessing."""


@dataclass(frozen=True)
class EvidenceResult:
    name: str
    verdict: str
    required: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FeedbackItem:
    kind: str
    identifier: str
    disposition: str
    body: str
    url: str | None
    rationale: str | None = None
    follow_up: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "disposition": self.disposition,
            "body": self.body,
            "url": self.url,
            "rationale": self.rationale,
            "follow_up": self.follow_up,
        }


@dataclass(frozen=True)
class AcceptanceFence:
    report_digest: str
    semantic_digest: str
    mailbox_revision: str
    receipt_id: str
    candidate_revision: str
    observed_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_digest": self.report_digest,
            "semantic_digest": self.semantic_digest,
            "mailbox_revision": self.mailbox_revision,
            "receipt_id": self.receipt_id,
            "candidate_revision": self.candidate_revision,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class AuditReport:
    work_id: str
    mailbox_revision: str
    work_status: str
    receipt_id: str
    candidate_revision: str
    comparison_base_revision: str
    approved_policy_commit: str
    current_policy_commit: str | None
    observed_at: str | None
    ticket_verdict: str
    ticket_detail: str
    acceptance_commit: str | None
    evidence: tuple[EvidenceResult, ...]
    feedback: tuple[FeedbackItem, ...]
    audit_evidence: Mapping[str, Any] | None
    authority_errors: tuple[str, ...]

    @property
    def overall_verdict(self) -> str:
        if self.authority_errors:
            return "authority-unreconstructable"
        if self.ticket_verdict != "satisfied":
            return self.ticket_verdict
        required = [item.verdict for item in self.evidence if item.required]
        for verdict in ("violated", "stale", "unknown"):
            if verdict in required:
                return verdict
        if self.work_status == "delivered":
            return "needs-decision"
        return "satisfied"

    @property
    def acceptance_possible(self) -> bool:
        return (
            self.work_status == "delivered"
            and not self.authority_errors
            and self.ticket_verdict == "satisfied"
            and all(item.verdict == "satisfied" for item in self.evidence if item.required)
        )

    def as_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        value = {
            "schema": "atelier.audit-report/v1",
            "work_id": self.work_id,
            "mailbox_revision": self.mailbox_revision,
            "work_status": self.work_status,
            "receipt_id": self.receipt_id,
            "candidate_revision": self.candidate_revision,
            "comparison_base_revision": self.comparison_base_revision,
            "approved_policy_commit": self.approved_policy_commit,
            "current_policy_commit": self.current_policy_commit,
            "observed_at": self.observed_at,
            "ticket": {
                "verdict": self.ticket_verdict,
                "detail": self.ticket_detail,
            },
            "acceptance_commit": self.acceptance_commit,
            "evidence": [item.as_dict() for item in self.evidence],
            "feedback": [item.as_dict() for item in self.feedback],
            "audit_evidence": copy.deepcopy(self.audit_evidence),
            "authority_errors": list(self.authority_errors),
            "overall_verdict": self.overall_verdict,
            "acceptance_possible": self.acceptance_possible,
        }
        if include_digest:
            value["report_digest"] = self.digest
            value["acceptance_fence"] = self.fence.as_dict()
        return value

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.as_dict(include_digest=False),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def semantic_digest(self) -> str:
        value = self.as_dict(include_digest=False)
        value["observed_at"] = None
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def fence(self) -> AcceptanceFence:
        return AcceptanceFence(
            report_digest=self.digest,
            semantic_digest=self.semantic_digest,
            mailbox_revision=self.mailbox_revision,
            receipt_id=self.receipt_id,
            candidate_revision=self.candidate_revision,
            observed_at=self.observed_at,
        )


class AuditCoordinator:
    """Reconstruct one delivery promise and record a separately confirmed acceptance."""

    def __init__(self, claims: ClaimCoordinator):
        self.claims = claims

    def audit(
        self,
        work_id: str,
        *,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        audit_evidence: Mapping[str, Any] | None,
        now: datetime | None = None,
    ) -> AuditReport:
        return self.claims.writer.observe(
            "audit delivery",
            lambda context: self._report(
                context,
                work_id,
                policy_target=policy_target,
                host_target=host_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                audit_evidence=audit_evidence,
                now=now,
            ),
        )

    def accept(
        self,
        work_id: str,
        fence: AcceptanceFence,
        *,
        confirmed: bool,
        accepted_at: datetime,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        audit_evidence: Mapping[str, Any],
        now: datetime | None = None,
    ) -> WriteResult:
        if not confirmed:
            raise MailboxTransitionRejected("operator acceptance was not explicitly confirmed")
        if accepted_at.utcoffset() is None:
            raise AuditError("accepted_at must include a UTC offset")
        if observation_not_before.utcoffset() is None:
            raise AuditError("observation_not_before must include a UTC offset")
        if fence.observed_at is None:
            raise MailboxTransitionRejected("confirmed audit has no live observation")
        if observation_not_before <= _parse_timestamp(fence.observed_at):
            raise AuditError("acceptance requires a new read boundary after the confirmed audit")
        if accepted_at < observation_not_before:
            raise AuditError("accepted_at cannot precede the live observation boundary")
        current_time = now or datetime.now(UTC)
        if current_time.utcoffset() is None:
            raise AuditError("now must include a UTC offset")
        if accepted_at > current_time:
            raise AuditError("accepted_at cannot be in the future")
        planned: dict[str, Any] = {}

        def revalidate(context: TransitionContext) -> None:
            report = self._report(
                context,
                work_id,
                policy_target=policy_target,
                host_target=host_target,
                observation_path=observation_path,
                observation_not_before=observation_not_before,
                audit_evidence=audit_evidence,
                now=now,
            )
            confirmed_value = report.as_dict(include_digest=False)
            confirmed_value["observed_at"] = fence.observed_at
            confirmed_digest = hashlib.sha256(
                json.dumps(
                    confirmed_value,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if (
                confirmed_digest != fence.report_digest
                or report.mailbox_revision != fence.mailbox_revision
                or report.receipt_id != fence.receipt_id
                or report.candidate_revision != fence.candidate_revision
                or report.semantic_digest != fence.semantic_digest
            ):
                raise MailboxTransitionRejected(
                    "current audit does not match the explicitly confirmed acceptance fence"
                )
            if report.observed_at is None or _parse_timestamp(
                report.observed_at
            ) <= _parse_timestamp(fence.observed_at):
                raise MailboxTransitionRejected(
                    "acceptance observation is not newer than the confirmed audit"
                )
            if report.observed_at is not None and accepted_at < _parse_timestamp(
                report.observed_at
            ):
                raise MailboxTransitionRejected(
                    "operator acceptance cannot precede the current live observation"
                )
            if not report.acceptance_possible:
                raise MailboxTransitionRejected(
                    f"acceptance is blocked by current audit verdict {report.overall_verdict}"
                )
            work, body = _read_work(context.checkout, work_id)
            if work["status"] != "delivered" or work["acceptance"] is not None:
                raise MailboxTransitionRejected(f"{work_id}: work is not awaiting acceptance")
            current_policy_commit = report.current_policy_commit
            if current_policy_commit is None:
                raise MailboxTransitionRejected("current policy identity is unavailable")
            accepted = copy.deepcopy(work)
            accepted["status"] = "accepted"
            accepted["claim"] = None
            accepted["acceptance"] = {
                "receipt_id": report.receipt_id,
                "accepted_by": "operator",
                "accepted_at": _timestamp(accepted_at),
                "policy_commit": current_policy_commit,
                "candidate_revision": report.candidate_revision,
                "evidence": {
                    item.name: "satisfied"
                    for item in report.evidence
                    if item.required
                },
                "audit_evidence": copy.deepcopy(report.audit_evidence),
            }
            planned.clear()
            planned.update(work=accepted, body=body)

        def plan(context: TransitionContext) -> TransitionPlan:
            del context
            return TransitionPlan(
                commit_message=f"accept delivered work {work_id}",
                changes=(
                    FileChange(
                        _work_path(work_id),
                        _render_document(planned["work"], planned["body"]),
                    ),
                ),
            )

        return self.claims.writer.publish(
            "accept delivery",
            revalidate=revalidate,
            plan=plan,
        )

    def _report(
        self,
        context: TransitionContext,
        work_id: str,
        *,
        policy_target: PolicyTarget,
        host_target: HostTarget,
        observation_path: Path,
        observation_not_before: datetime,
        audit_evidence: Mapping[str, Any] | None,
        now: datetime | None,
    ) -> AuditReport:
        work, body = _read_work(context.checkout, work_id)
        if work["status"] not in {"delivered", "accepted"}:
            raise MailboxTransitionRejected(
                f"{work_id}: audit requires delivered or accepted work"
            )
        receipt_id = work["delivery_receipt_id"]
        if receipt_id is None:
            raise MailboxTransitionRejected(f"{work_id}: delivery receipt is missing")
        receipt, _ = _read_yaml(
            context.checkout / f"work/{work_id}/receipts/{receipt_id}.md",
            frontmatter=True,
            label=f"work/{work_id}/receipts/{receipt_id}.md",
        )
        candidate = receipt["candidate"]
        if candidate is None:
            raise MailboxTransitionRejected(f"{work_id}: delivery candidate is missing")
        approval = work["approval"]
        if approval is None:
            raise MailboxTransitionRejected(f"{work_id}: approved contract is missing")
        project = _read_project(context.checkout, work["project_id"])
        authority_errors: list[str] = []
        observation: dict[str, Any] | None = None
        effective_policy: dict[str, Any] | None = None
        current_policy_commit: str | None = None
        effective_audit_evidence: dict[str, Any] | None = None

        try:
            self.claims._verify_capability(host_target)
        except Exception as error:
            authority_errors.append(f"host capability: {error}")
        try:
            observation = _validated_observation(
                observation_path,
                not_before=observation_not_before,
                now=now,
            )
        except Exception as error:
            authority_errors.append(f"live GitHub observation: {error}")
        try:
            self.claims._require_approved_commit(
                context,
                work_id,
                work,
                body,
                receipt["approved_commit"],
            )
            if not self.claims.policy_remote_verifier(
                policy_target,
                project["repository"],
            ):
                raise AuditError(
                    "policy remote is foreign or unverifiable for the managed project"
                )
            approved_policy = _read_policy_at_commit(
                policy_target,
                approval["policy"]["commit"],
            )
            current_policy = _read_current_policy(policy_target)
            effective_policy = _effective_policy(approved_policy, current_policy.value)
            _require_policy_identity(
                effective_policy,
                current_policy,
                project=project,
                work=work,
                mailbox_remote=self.claims.remote,
                mailbox_branch=self.claims.branch,
                mailbox_realm=context.snapshot["realm_id"],
                approval=approval,
            )
            current_policy_commit = current_policy.commit
        except Exception as error:
            authority_errors.append(f"project policy: {error}")

        supplied_audit_evidence = (
            work["acceptance"]["audit_evidence"]
            if work["status"] == "accepted" and work["acceptance"] is not None
            else audit_evidence
        )
        try:
            effective_audit_evidence = _validated_audit_evidence(supplied_audit_evidence)
        except Exception as error:
            authority_errors.append(f"audit evidence: {error}")
        acceptance_commit, baseline_ticket_digest = _acceptance_history(
            context,
            work_id,
            work,
        )
        if baseline_ticket_digest is None:
            authority_errors.append("delivery ticket observation is unreconstructable")
        ticket_verdict, ticket_detail = _ticket_verdict(
            work,
            project,
            observation,
            effective_policy,
            baseline_ticket_digest,
        )
        required_evidence = tuple(
            (
                effective_policy["acceptance"]["evidence"]
                if effective_policy is not None
                else approval["acceptance"]["required_evidence"]
            )
        )
        verdicts = _evaluate_evidence(
            candidate,
            receipt,
            observation,
            effective_policy,
            effective_audit_evidence,
            self.claims,
        )
        feedback = _feedback_items(receipt, observation, effective_audit_evidence)
        return AuditReport(
            work_id=work_id,
            mailbox_revision=context.base_revision,
            work_status=work["status"],
            receipt_id=receipt_id,
            candidate_revision=candidate["head_revision"],
            comparison_base_revision=candidate["base_revision"],
            approved_policy_commit=approval["policy"]["commit"],
            current_policy_commit=current_policy_commit,
            observed_at=observation["observed_at"] if observation is not None else None,
            ticket_verdict=ticket_verdict,
            ticket_detail=ticket_detail,
            acceptance_commit=acceptance_commit,
            evidence=tuple(
                EvidenceResult(
                    name=name,
                    verdict=verdicts[name][0],
                    required=(
                        name in required_evidence or name == "unresolved-feedback-zero"
                    ),
                    detail=verdicts[name][1],
                )
                for name in EVIDENCE_NAMES
            ),
            feedback=feedback,
            audit_evidence=effective_audit_evidence,
            authority_errors=tuple(authority_errors),
        )


def _acceptance_history(
    context: TransitionContext,
    work_id: str,
    work: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    if work["status"] == "delivered":
        claim = work["claim"]
        return (
            None,
            claim["ticket_observation_digest"] if claim is not None else None,
        )
    acceptance = work["acceptance"]
    if acceptance is None:
        return None, None
    path = _work_path(work_id)
    history = run_git(
        context.checkout,
        ("log", "--format=%H", "--", path),
    )
    if history.returncode != 0:
        return None, None
    for commit in history.stdout.splitlines():
        try:
            current, _ = _read_work_at(context.checkout, commit, path)
        except Exception:
            continue
        if current["acceptance"] != acceptance:
            continue
        parent = run_git(context.checkout, ("rev-parse", f"{commit}^"))
        if parent.returncode != 0:
            continue
        try:
            previous, _ = _read_work_at(
                context.checkout,
                parent.stdout.strip(),
                path,
            )
        except Exception:
            continue
        if previous["acceptance"] is None:
            claim = previous["claim"]
            return (
                commit,
                claim["ticket_observation_digest"] if claim is not None else None,
            )
    return None, None


def _ticket_verdict(
    work: Mapping[str, Any],
    project: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    policy: Mapping[str, Any] | None,
    baseline_digest: str | None,
) -> tuple[str, str]:
    if observation is None:
        return "unknown", "current native ticket state is unavailable"
    repository = observation["repository"]["name_with_owner"]
    if repository != project["repository"].removeprefix("github:"):
        return "violated", "live repository does not identify the managed project"
    ticket = work["native_ticket"]
    issue = observation["issue"]
    if (
        ticket is None
        or ticket["provider"] != "github"
        or ticket["id"] != str(issue["number"])
        or ticket["url"] != issue["url"]
    ):
        return "violated", "live native ticket does not identify the approved assignment"
    if policy is None:
        return "unknown", "effective project policy is unavailable"
    if issue["state"].lower() not in policy["ticket"]["allowed_states"]:
        return "violated", f"ticket state {issue['state']} is not allowed"
    if policy["ticket"]["require_no_blockers"]:
        blockers = [item for item in issue["blocked_by"] if item["state"] != "CLOSED"]
        if blockers:
            numbers = ", ".join(f"#{item['number']}" for item in blockers)
            return "violated", f"native ticket has unresolved blockers: {numbers}"
    current_digest = _ticket_material_digest(issue, policy)
    if baseline_digest is None:
        return "unknown", "delivery ticket observation cannot be reconstructed"
    if current_digest != baseline_digest:
        return "stale", "material native ticket state changed after the delivery observation"
    return "satisfied", "native ticket identity, eligibility, and material state are current"


def _validated_audit_evidence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditError("a normalized audit-evidence record is required")
    _require_exact_keys(value, {"schema", "review", "feedback_dispositions"}, "record")
    if value["schema"] != "atelier.audit-evidence/v1":
        raise AuditError("unsupported audit-evidence schema")
    review = value["review"]
    if not isinstance(review, Mapping):
        raise AuditError("audit review must be an object")
    _require_exact_keys(
        review,
        {
            "mechanism",
            "verdict",
            "candidate_revision",
            "comparison_base_revision",
            "observed_at",
            "findings",
        },
        "review",
    )
    if review["mechanism"] != "review-code-change":
        raise AuditError("audit review must use review-code-change")
    if review["verdict"] not in {"clean", "changes_required", "blocked"}:
        raise AuditError("audit review verdict is invalid")
    for name in ("candidate_revision", "comparison_base_revision"):
        revision = review[name]
        if (
            not isinstance(revision, str)
            or len(revision) != 40
            or any(character not in "0123456789abcdef" for character in revision)
        ):
            raise AuditError(f"audit review {name} must be a lowercase Git SHA")
    if not isinstance(review["observed_at"], str):
        raise AuditError("audit review observed_at must be a timestamp")
    _parse_timestamp(review["observed_at"])
    if not isinstance(review["findings"], list):
        raise AuditError("audit review findings must be a list")
    finding_ids: set[str] = set()
    for finding in review["findings"]:
        _validate_disposition(
            finding,
            kind="review finding",
            required={"id", "summary", "disposition", "rationale", "follow_up"},
            dispositions={"fixed", "deferred", "not-actionable", "unresolved"},
        )
        if finding["id"] in finding_ids:
            raise AuditError(f"duplicate review finding {finding['id']}")
        finding_ids.add(finding["id"])
    dispositions = value["feedback_dispositions"]
    if not isinstance(dispositions, list):
        raise AuditError("feedback dispositions must be a list")
    disposition_ids: set[tuple[str, str]] = set()
    for disposition in dispositions:
        _validate_disposition(
            disposition,
            kind="feedback disposition",
            required={
                "kind",
                "id",
                "body_digest",
                "disposition",
                "rationale",
                "follow_up",
            },
            dispositions={"resolved", "deferred", "not-actionable", "unresolved"},
        )
        if disposition["kind"] not in {"review", "pull-request-comment"}:
            raise AuditError("feedback disposition kind is invalid")
        body_digest = disposition["body_digest"]
        if (
            not body_digest.startswith("sha256:")
            or len(body_digest) != 71
            or any(character not in "0123456789abcdef" for character in body_digest[7:])
        ):
            raise AuditError("feedback disposition body_digest is invalid")
        identity = (disposition["kind"], disposition["id"])
        if identity in disposition_ids:
            raise AuditError(f"duplicate feedback disposition {identity[0]} {identity[1]}")
        disposition_ids.add(identity)
    return copy.deepcopy(dict(value))


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise AuditError(f"{label} fields do not match the v1 contract")


def _validate_disposition(
    value: Any,
    *,
    kind: str,
    required: set[str],
    dispositions: set[str],
) -> None:
    if not isinstance(value, Mapping):
        raise AuditError(f"{kind} must be an object")
    _require_exact_keys(value, required, kind)
    for name in required - {"follow_up", "disposition"}:
        if not isinstance(value[name], str) or not value[name].strip():
            raise AuditError(f"{kind} {name} must be nonempty")
    if value["disposition"] not in dispositions:
        raise AuditError(f"{kind} disposition is invalid")
    if value["follow_up"] is not None and not isinstance(value["follow_up"], str):
        raise AuditError(f"{kind} follow_up must be text or null")



def _body_digest(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()

def _evaluate_evidence(
    candidate: Mapping[str, Any],
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    policy: Mapping[str, Any] | None,
    audit_evidence: Mapping[str, Any] | None,
    claims: ClaimCoordinator,
) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {}
    try:
        reachable = claims.candidate_verifier(candidate)
    except Exception as error:
        values["candidate-remote-reachable"] = (
            "unknown",
            f"candidate remote cannot be read: {error}",
        )
    else:
        values["candidate-remote-reachable"] = (
            "satisfied" if reachable else "violated",
            (
                "delivered SHA is reachable from the declared remote ref"
                if reachable
                else "declared remote ref does not contain the delivered SHA"
            ),
        )

    pull_request = observation["pull_request"] if observation is not None else None
    live_base_current = False
    if observation is None:
        for name in (
            "pull-request-head-current",
            "pull-request-open",
            "pull-request-mergeable",
            "required-checks-pass",
            "unresolved-feedback-zero",
        ):
            values[name] = ("unknown", "current GitHub state is unavailable")
    elif pull_request is None:
        values["pull-request-head-current"] = (
            "violated",
            "delivered pull request no longer exists in the live observation",
        )
        values["pull-request-open"] = ("violated", "delivered pull request is absent")
        values["pull-request-mergeable"] = (
            "unknown",
            "mergeability is unavailable without a live pull request",
        )
        values["required-checks-pass"] = (
            "unknown",
            "required check results are unavailable without a live pull request",
        )
        values["unresolved-feedback-zero"] = (
            "unknown",
            "thread-aware feedback is unavailable without a live pull request",
        )
    else:
        expected_repository = candidate["repository"].removeprefix("github:")
        live_head = pull_request["head"]
        live_base = pull_request["base"]
        same_pr = pull_request["url"] == candidate["pull_request"]
        same_repository_ref = (
            live_head["repository"] == expected_repository
            and live_head["ref"] == candidate["remote_ref"]
        )
        same_head = live_head["sha"] == candidate["head_revision"]
        live_base_current = bool(
            policy is not None
            and live_base["repository"] == expected_repository
            and live_base["ref"] == policy["repository"]["canonical_ref"]
            and live_base["sha"] == candidate["base_revision"]
        )
        if not same_pr or not same_repository_ref:
            values["pull-request-head-current"] = (
                "violated",
                "live pull request repository, ref, or URL differs from the delivery",
            )
        elif not same_head:
            values["pull-request-head-current"] = (
                "stale",
                "live pull request head changed after delivery",
            )
        else:
            values["pull-request-head-current"] = (
                "satisfied",
                "live pull request repository, ref, and head match the delivery",
            )
        values["pull-request-open"] = (
            (
                "satisfied",
                "live pull request is open",
            )
            if pull_request["state"] == "OPEN"
            else (
                "violated",
                f"live pull request state is {pull_request['state']}",
            )
        )
        if not same_head or not live_base_current:
            values["pull-request-mergeable"] = (
                "stale",
                "mergeability belongs to a different pull request head or base",
            )
        elif pull_request["mergeable"] == "MERGEABLE":
            values["pull-request-mergeable"] = (
                "satisfied",
                "GitHub reports the exact delivered head mergeable",
            )
        elif pull_request["mergeable"] == "CONFLICTING":
            values["pull-request-mergeable"] = (
                "violated",
                "GitHub reports a merge conflict",
            )
        else:
            values["pull-request-mergeable"] = (
                "unknown",
                "GitHub mergeability is unavailable",
            )
        values["required-checks-pass"] = _checks_verdict(
            observation["checks"],
            observation["required_checks"],
            candidate["head_revision"],
        )
        values["unresolved-feedback-zero"] = _feedback_verdict(
            receipt,
            observation,
            audit_evidence,
        )

    values["required-validation-reported"] = _validation_verdict(
        receipt,
        candidate["head_revision"],
        (
            policy["validation"]["required_commands"]
            if policy is not None
            else ()
        ),
    )
    values["independent-review-current"] = _review_verdict(
        receipt,
        audit_evidence,
        candidate["head_revision"],
        candidate["base_revision"],
    )
    if pull_request is not None and not live_base_current:
        values["independent-review-current"] = (
            "stale",
            "the live pull request base differs from the reviewed delivery base",
        )
    return values


def _checks_verdict(
    checks: Sequence[Mapping[str, Any]],
    required: Mapping[str, Any],
    candidate_revision: str,
) -> tuple[str, str]:
    if not required["configuration_read"]:
        return "unknown", "effective required-check configuration could not be read"
    observed_by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for check in checks:
        observed_by_identity.setdefault((check["kind"], check["name"]), []).append(check)
    selected: list[Mapping[str, Any]] = []
    for context in required["contexts"]:
        matches = observed_by_identity.get((context["kind"], context["name"]), [])
        if len(matches) != 1:
            return "unknown", "a required check context is missing or ambiguous"
        selected.append(matches[0])
    if any(check["candidate_sha"] != candidate_revision for check in selected):
        return "stale", "one or more required checks belong to another candidate"
    incomplete = [
        check
        for check in selected
        if check["status"].upper() != "COMPLETED" or check["conclusion"] is None
    ]
    if incomplete:
        return "unknown", "one or more required check results are incomplete"
    failing = [
        check
        for check in selected
        if check["conclusion"].upper() not in {"SUCCESS", "NEUTRAL", "SKIPPED"}
    ]
    if failing:
        return "violated", "one or more required checks completed unsuccessfully"
    if not selected:
        return "satisfied", "required-check configuration was read and names no contexts"
    return "satisfied", "every configured required check passed on the delivered head"


def _validation_verdict(
    receipt: Mapping[str, Any],
    candidate_revision: str,
    required_commands: Sequence[str],
) -> tuple[str, str]:
    observations = {
        item["command"]: item
        for item in receipt["validation"]
        if item["command"] in required_commands
    }
    missing = [command for command in required_commands if command not in observations]
    if missing:
        return "unknown", f"required validation is missing: {', '.join(missing)}"
    selected = [observations[command] for command in required_commands]
    if any(item["candidate_revision"] != candidate_revision for item in selected):
        return "stale", "required validation belongs to another candidate"
    if any(item["outcome"] != "passed" for item in selected):
        return "violated", "one or more required validation commands failed"
    return "satisfied", "every effective required command passed on the delivered head"


def _review_verdict(
    receipt: Mapping[str, Any],
    audit_evidence: Mapping[str, Any] | None,
    candidate_revision: str,
    comparison_base_revision: str,
) -> tuple[str, str]:
    reviews = [
        item
        for item in receipt["reviews"]
        if item["mechanism"] == "review-code-change"
    ]
    if not reviews or audit_evidence is None:
        return "unknown", "structured independent review evidence is missing"
    dated = [(_parse_timestamp(item["observed_at"]), item) for item in reviews]
    latest_time = max(observed_at for observed_at, _ in dated)
    latest = [item for observed_at, item in dated if observed_at == latest_time]
    review = audit_evidence["review"]
    if any(
        item["candidate_revision"] != candidate_revision
        or item["comparison_base_revision"] != comparison_base_revision
        for item in latest
    ) or (
        review["candidate_revision"] != candidate_revision
        or review["comparison_base_revision"] != comparison_base_revision
    ):
        return "stale", "independent review belongs to another head or base"
    receipt_verdicts = {item["verdict"] for item in latest}
    if "changes_required" in receipt_verdicts or review["verdict"] == "changes_required":
        return "violated", "independent review requires changes"
    if review["verdict"] == "blocked" or receipt_verdicts != {"clean"}:
        return "unknown", "independent review is blocked or contradictory"
    if any(item["disposition"] == "unresolved" for item in review["findings"]):
        return "violated", "independent review retains an unresolved finding"
    return (
        "satisfied",
        "structured independent review is clean on the exact head and base",
    )


def _feedback_verdict(
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any],
    audit_evidence: Mapping[str, Any] | None,
) -> tuple[str, str]:
    unresolved_threads = [
        item
        for item in observation["threads"]
        if not item["is_resolved"] and not item["is_outdated"]
    ]
    if unresolved_threads:
        return "violated", "one or more live review threads remain unresolved"
    pull_request = observation["pull_request"]
    if pull_request is not None and pull_request["review_decision"] == "CHANGES_REQUESTED":
        return "violated", "the live pull request review decision requires changes"
    if receipt["unresolved_obligations"]:
        return "violated", "the delivered receipt retains unresolved obligations"
    live_feedback = {
        (kind, item["id"]): _body_digest(item["body"])
        for kind, collection in (
            ("review", observation["reviews"]),
            ("pull-request-comment", observation["pull_request_comments"]),
        )
        for item in collection
        if item["body"].strip()
    }
    dispositions = {
        (item["kind"], item["id"]): item
        for item in (
            audit_evidence["feedback_dispositions"] if audit_evidence is not None else ()
        )
    }
    if set(dispositions) - set(live_feedback):
        return "stale", "a feedback disposition does not identify current live feedback"
    if any(
        item["body_digest"] != live_feedback[identity]
        for identity, item in dispositions.items()
    ):
        return "stale", "a feedback disposition belongs to an earlier body revision"
    missing = set(live_feedback) - set(dispositions)
    if missing:
        return "unknown", "one or more live review or comment bodies lack a disposition"
    if any(item["disposition"] == "unresolved" for item in dispositions.values()):
        return "violated", "one or more live review or comment bodies remain unresolved"
    return (
        "satisfied",
        "every material obligation, review, comment, and thread has a durable disposition",
    )


def _feedback_items(
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    audit_evidence: Mapping[str, Any] | None,
) -> tuple[FeedbackItem, ...]:
    items = [
        FeedbackItem(
            kind="receipt-obligation",
            identifier=f"obligation-{index}",
            disposition="unresolved",
            body=value,
            url=None,
        )
        for index, value in enumerate(receipt["unresolved_obligations"], start=1)
    ]
    if observation is None:
        return tuple(items)
    dispositions = {
        (item["kind"], item["id"]): item
        for item in (
            audit_evidence["feedback_dispositions"] if audit_evidence is not None else ()
        )
    }
    for kind, collection in (
        ("review", observation["reviews"]),
        ("pull-request-comment", observation["pull_request_comments"]),
    ):
        for value in collection:
            disposition = dispositions.get((kind, value["id"]))
            items.append(
                FeedbackItem(
                    kind=kind,
                    identifier=value["id"],
                    disposition=(
                        disposition["disposition"]
                        if disposition is not None
                        else "undispositioned"
                        if value["body"].strip()
                        else "no-material-body"
                    ),
                    body=value["body"],
                    url=value["url"],
                    rationale=(disposition["rationale"] if disposition is not None else None),
                    follow_up=(disposition["follow_up"] if disposition is not None else None),
                )
            )
    items.extend(
        FeedbackItem(
            kind="review-thread",
            identifier=thread["id"],
            disposition=(
                "resolved"
                if thread["is_resolved"]
                else "outdated"
                if thread["is_outdated"]
                else "unresolved"
            ),
            body="\n\n".join(comment["body"] for comment in thread["comments"]),
            url=thread["comments"][-1]["url"],
        )
        for thread in observation["threads"]
    )
    return tuple(items)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise AuditError("timestamps must include a UTC offset")
    return parsed


def _json_object(value: str, label: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise AuditError(f"{label} must be a JSON object")
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


def _fence(value: Mapping[str, Any]) -> AcceptanceFence:
    return AcceptanceFence(
        report_digest=value["report_digest"],
        semantic_digest=value["semantic_digest"],
        mailbox_revision=value["mailbox_revision"],
        receipt_id=value["receipt_id"],
        candidate_revision=value["candidate_revision"],
        observed_at=value["observed_at"],
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "accept"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--mailbox-remote", required=True)
        subparser.add_argument("--mailbox-branch", required=True)
        subparser.add_argument("--work-id", required=True)
        subparser.add_argument("--policy-target", required=True)
        subparser.add_argument("--host-target", required=True)
        subparser.add_argument("--observation", required=True, type=Path)
        subparser.add_argument("--observation-not-before", required=True)
        subparser.add_argument("--audit-evidence", required=True, type=Path)
        subparser.add_argument("--now")
    accept = subparsers.choices["accept"]
    accept.add_argument("--fence", required=True)
    accept.add_argument("--accepted-at", required=True)
    accept.add_argument("--confirm", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    claims = ClaimCoordinator(parsed.mailbox_remote, parsed.mailbox_branch)
    coordinator = AuditCoordinator(claims)
    common = {
        "policy_target": _policy_target(
            _json_object(parsed.policy_target, "policy target")
        ),
        "host_target": _host_target(
            _json_object(parsed.host_target, "host target")
        ),
        "observation_path": parsed.observation,
        "observation_not_before": _parse_timestamp(
            parsed.observation_not_before
        ),
        "audit_evidence": _json_object(
            parsed.audit_evidence.read_text(encoding="utf-8"),
            "audit evidence",
        ),
        "now": _parse_timestamp(parsed.now) if parsed.now else None,
    }
    try:
        if parsed.command == "audit":
            value = coordinator.audit(parsed.work_id, **common).as_dict()
        else:
            result = coordinator.accept(
                parsed.work_id,
                _fence(_json_object(parsed.fence, "acceptance fence")),
                confirmed=parsed.confirm,
                accepted_at=_parse_timestamp(parsed.accepted_at),
                **common,
            )
            value = {
                "operation": result.operation,
                "branch": result.branch,
                "commit": result.commit,
                "base_revision": result.base_revision,
                "attempts": result.attempts,
                "recovered": result.recovered,
            }
    except (
        AuditError,
        MailboxTransitionRejected,
        PlanningError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
