#!/usr/bin/env python3
"""Live delivery audit and explicit operator acceptance for Atelier v0."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "disposition": self.disposition,
            "body": self.body,
            "url": self.url,
        }


@dataclass(frozen=True)
class AcceptanceFence:
    report_digest: str
    mailbox_revision: str
    receipt_id: str
    candidate_revision: str

    def as_dict(self) -> dict[str, str]:
        return {
            "report_digest": self.report_digest,
            "mailbox_revision": self.mailbox_revision,
            "receipt_id": self.receipt_id,
            "candidate_revision": self.candidate_revision,
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
    def fence(self) -> AcceptanceFence:
        return AcceptanceFence(
            report_digest=self.digest,
            mailbox_revision=self.mailbox_revision,
            receipt_id=self.receipt_id,
            candidate_revision=self.candidate_revision,
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
        now: datetime | None = None,
    ) -> WriteResult:
        if not confirmed:
            raise MailboxTransitionRejected("operator acceptance was not explicitly confirmed")
        if accepted_at.utcoffset() is None:
            raise AuditError("accepted_at must include a UTC offset")
        if observation_not_before.utcoffset() is None:
            raise AuditError("observation_not_before must include a UTC offset")
        if accepted_at < observation_not_before:
            raise AuditError("accepted_at cannot precede the live observation boundary")
        if now is not None and accepted_at > now:
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
                now=now,
            )
            if report.fence != fence:
                raise MailboxTransitionRejected(
                    "current audit does not match the explicitly confirmed acceptance fence"
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
            self.claims,
        )
        feedback = _feedback_items(receipt, observation)
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
                    required=name in required_evidence,
                    detail=verdicts[name][1],
                )
                for name in EVIDENCE_NAMES
            ),
            feedback=feedback,
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


def _evaluate_evidence(
    candidate: Mapping[str, Any],
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    policy: Mapping[str, Any] | None,
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
        same_pr = pull_request["url"] == candidate["pull_request"]
        same_repository_ref = (
            live_head["repository"] == expected_repository
            and live_head["ref"] == candidate["remote_ref"]
        )
        same_head = live_head["sha"] == candidate["head_revision"]
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
        if not same_head:
            values["pull-request-mergeable"] = (
                "stale",
                "mergeability belongs to a different pull request head",
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
            candidate["head_revision"],
        )
        values["unresolved-feedback-zero"] = _feedback_verdict(
            receipt,
            observation,
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
        candidate["head_revision"],
        candidate["base_revision"],
    )
    return values


def _checks_verdict(
    checks: Sequence[Mapping[str, Any]],
    candidate_revision: str,
) -> tuple[str, str]:
    if any(check["candidate_sha"] != candidate_revision for check in checks):
        return "stale", "one or more required checks belong to another candidate"
    incomplete = [
        check
        for check in checks
        if check["status"].upper() != "COMPLETED" or check["conclusion"] is None
    ]
    if incomplete:
        return "unknown", "one or more required check results are incomplete"
    failing = [
        check
        for check in checks
        if check["conclusion"].upper() not in {"SUCCESS", "NEUTRAL", "SKIPPED"}
    ]
    if failing:
        return "violated", "one or more required checks completed unsuccessfully"
    return "satisfied", "all observed required checks passed on the delivered head"


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
    candidate_revision: str,
    comparison_base_revision: str,
) -> tuple[str, str]:
    reviews = [
        item
        for item in receipt["reviews"]
        if item["mechanism"] == "review-code-change"
    ]
    if not reviews:
        return "unknown", "independent review-code-change evidence is missing"
    dated = [(_parse_timestamp(item["observed_at"]), item) for item in reviews]
    latest_time = max(observed_at for observed_at, _ in dated)
    latest = [item for observed_at, item in dated if observed_at == latest_time]
    if any(
        item["candidate_revision"] != candidate_revision
        or item["comparison_base_revision"] != comparison_base_revision
        for item in latest
    ):
        return "stale", "latest independent review belongs to another head or base"
    verdicts = {item["verdict"] for item in latest}
    if verdicts == {"clean"}:
        return "satisfied", "latest independent review is clean on the exact head and base"
    if "changes_required" in verdicts:
        return "violated", "latest independent review requires changes"
    return "unknown", "latest independent review is blocked or contradictory"


def _feedback_verdict(
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any],
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
    return (
        "satisfied",
        "no unresolved material receipt obligation, review decision, or live thread remains",
    )


def _feedback_items(
    receipt: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
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
    items.extend(
        FeedbackItem(
            kind="review",
            identifier=review["id"],
            disposition=review["state"],
            body=review["body"],
            url=review["url"],
        )
        for review in observation["reviews"]
    )
    items.extend(
        FeedbackItem(
            kind="pull-request-comment",
            identifier=comment["id"],
            disposition="recorded",
            body=comment["body"],
            url=comment["url"],
        )
        for comment in observation["pull_request_comments"]
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
        mailbox_revision=value["mailbox_revision"],
        receipt_id=value["receipt_id"],
        candidate_revision=value["candidate_revision"],
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
