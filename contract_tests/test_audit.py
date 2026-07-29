from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta

from contract_tests import test_claiming
from skills.atelier.scripts.audit import AuditCoordinator, AuditError
from skills.atelier.scripts.git_mailbox import MailboxTransitionRejected
from skills.atelier.scripts.mailbox import _read_yaml, reconstruct_mailbox


class AuditContract(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_claiming.ClaimingContract(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.test_delegation_delivers_one_exact_ready_pull_request()
        self.audit = AuditCoordinator(self.fixture.coordinator)
        self.observation_not_before = self.fixture.live_at + timedelta(minutes=3)
        self.now = self.fixture.live_at + timedelta(minutes=4)
        self.read_count = 0
        self.audit_evidence = self.evidence()

    def evidence(
        self,
        *,
        findings: list[dict] | None = None,
        feedback_dispositions: list[dict] | None = None,
    ) -> dict:
        live = self.live_observation()
        return {
            "schema": "atelier.audit-evidence/v1",
            "review": {
                "mechanism": "review-code-change",
                "verdict": "clean",
                "candidate_revision": live["pull_request"]["head"]["sha"],
                "comparison_base_revision": live["pull_request"]["base"]["sha"],
                "observed_at": live["observed_at"],
                "findings": findings or [],
            },
            "feedback_dispositions": feedback_dispositions or [],
        }

    def report(self, *, evidence: dict | None = None):
        return self.audit.audit(
            self.fixture.work_id,
            policy_target=self.fixture.policy_target(),
            host_target=self.fixture.delegation_host_target(),
            observation_path=self.fixture.observation_path,
            observation_not_before=self.observation_not_before,
            audit_evidence=evidence or self.audit_evidence,
            now=self.now,
        )

    def accept(
        self,
        report,
        *,
        confirmed: bool = True,
        evidence: dict | None = None,
        refresh_observation: bool = True,
    ):
        boundary = datetime.fromisoformat(report.observed_at.replace("Z", "+00:00"))
        boundary += timedelta(seconds=1)
        if refresh_observation:
            live = self.live_observation()
            live["observed_at"] = boundary.isoformat().replace("+00:00", "Z")
            self.write_observation(live)
        return self.audit.accept(
            self.fixture.work_id,
            report.fence,
            confirmed=confirmed,
            accepted_at=self.now,
            policy_target=self.fixture.policy_target(),
            host_target=self.fixture.delegation_host_target(),
            observation_path=self.fixture.observation_path,
            observation_not_before=boundary,
            audit_evidence=evidence or self.audit_evidence,
            now=self.now,
        )

    def mailbox_main(self) -> str:
        return test_claiming.git(
            None,
            "--git-dir",
            str(self.fixture.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

    def current_work(self) -> dict:
        self.read_count += 1
        checkout = self.fixture.mailbox_clone(f"audit-read-{self.read_count}")
        work, _ = _read_yaml(
            checkout / f"work/{self.fixture.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        reconstruct_mailbox(checkout)
        return work

    def live_observation(self) -> dict:
        return json.loads(self.fixture.observation_path.read_text(encoding="utf-8"))

    def write_observation(self, value: dict) -> None:
        test_claiming.write_json(self.fixture.observation_path, value)

    def test_live_audit_and_explicit_acceptance_are_exact_and_distinct(self) -> None:
        report = self.report()
        self.assertEqual(report.overall_verdict, "needs-decision")
        self.assertTrue(report.acceptance_possible)
        self.assertEqual(report.work_status, "delivered")
        self.assertIsNone(report.acceptance_commit)
        self.assertEqual(
            {item.name: item.verdict for item in report.evidence if item.required},
            {
                name: "satisfied"
                for name in test_claiming.EVIDENCE
            },
        )

        write = self.accept(report)
        work = self.current_work()
        self.assertEqual(work["status"], "accepted")
        self.assertIsNone(work["claim"])
        self.assertEqual(work["acceptance"]["receipt_id"], report.receipt_id)
        self.assertEqual(
            work["acceptance"]["candidate_revision"],
            report.candidate_revision,
        )
        self.assertEqual(
            work["acceptance"]["evidence"],
            {
                name: "satisfied"
                for name in test_claiming.EVIDENCE
            },
        )
        self.assertEqual(work["acceptance"]["audit_evidence"], report.audit_evidence)
        self.assertEqual(work["delivery_receipt_id"], report.receipt_id)

        accepted = self.report()
        self.assertEqual(accepted.work_status, "accepted")
        self.assertEqual(accepted.overall_verdict, "satisfied")
        self.assertEqual(accepted.acceptance_commit, write.commit)

    def test_acceptance_requires_the_explicit_current_audit_fence(self) -> None:
        report = self.report()
        before = self.mailbox_main()
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "operator acceptance was not explicitly confirmed",
        ):
            self.accept(report, confirmed=False)
        self.assertEqual(self.mailbox_main(), before)
        changed = self.live_observation()
        changed["pull_request"]["head"]["sha"] = "c" * 40
        for check in changed["checks"]:
            check["candidate_sha"] = "c" * 40
        self.write_observation(changed)
        before = self.mailbox_main()

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "current audit does not match the explicitly confirmed acceptance fence",
        ):
            self.accept(report)
        self.assertEqual(self.mailbox_main(), before)

    def test_unknown_or_violated_evidence_cannot_be_accepted(self) -> None:
        unknown_path = self.fixture.root / "missing-observation.json"
        unknown = self.audit.audit(
            self.fixture.work_id,
            policy_target=self.fixture.policy_target(),
            host_target=self.fixture.delegation_host_target(),
            observation_path=unknown_path,
            observation_not_before=self.observation_not_before,
            audit_evidence=self.audit_evidence,
            now=self.now,
        )
        self.assertEqual(unknown.overall_verdict, "authority-unreconstructable")
        self.assertFalse(unknown.acceptance_possible)
        self.assertEqual(
            {
                item.verdict
                for item in unknown.evidence
                if item.name
                in {
                    "pull-request-head-current",
                    "pull-request-open",
                    "pull-request-mergeable",
                    "required-checks-pass",
                    "unresolved-feedback-zero",
                }
            },
            {"unknown"},
        )

        live = self.live_observation()
        live["pull_request"]["mergeable"] = "CONFLICTING"
        live["threads"] = [
            {
                "id": "thread-1",
                "pull_request_number": live["pull_request"]["number"],
                "is_resolved": False,
                "is_outdated": False,
                "path": "example.py",
                "line": 1,
                "start_line": 1,
                "comments": [
                    {
                        "id": "thread-comment-1",
                        "author": "reviewer",
                        "body": "This material concern still needs a decision.",
                        "created_at": live["observed_at"],
                        "updated_at": live["observed_at"],
                        "url": live["pull_request"]["url"] + "#discussion_r1",
                    }
                ],
            }
        ]
        self.write_observation(live)
        violated = self.report()
        feedback = {
            item.name: item.verdict
            for item in violated.evidence
        }
        self.assertEqual(feedback["unresolved-feedback-zero"], "violated")
        self.assertFalse(violated.acceptance_possible)
        before = self.mailbox_main()
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "acceptance is blocked by current audit verdict violated",
        ):
            self.accept(violated)
        self.assertEqual(self.mailbox_main(), before)

    def test_material_ticket_drift_is_stale_and_blocks_acceptance(self) -> None:
        live = self.live_observation()
        live["issue"]["body"] += "\n\nMaterial contract change."
        self.write_observation(live)

        report = self.report()
        self.assertEqual(report.ticket_verdict, "stale")
        self.assertEqual(report.overall_verdict, "stale")
        self.assertFalse(report.acceptance_possible)
        before = self.mailbox_main()
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "acceptance is blocked by current audit verdict stale",
        ):
            self.accept(report)
        self.assertEqual(self.mailbox_main(), before)

    def test_review_dispositions_remain_visible_without_becoming_failure(self) -> None:
        live = self.live_observation()
        live["pull_request_comments"] = [
            {
                "id": "comment-1",
                "author": "reviewer",
                "body": "P3 deferred to a focused follow-up.",
                "created_at": live["observed_at"],
                "updated_at": live["observed_at"],
                "url": live["pull_request"]["url"] + "#issuecomment-1",
            }
        ]
        live["threads"] = [
            {
                "id": "thread-1",
                "pull_request_number": live["pull_request"]["number"],
                "is_resolved": True,
                "is_outdated": False,
                "path": "example.py",
                "line": 1,
                "start_line": 1,
                "comments": [
                    {
                        "id": "thread-comment-1",
                        "author": "reviewer",
                        "body": "Deliberately deferred; the delivery remains clean.",
                        "created_at": live["observed_at"],
                        "updated_at": live["observed_at"],
                        "url": live["pull_request"]["url"] + "#discussion_r1",
                    }
                ],
            }
        ]
        self.write_observation(live)
        evidence = self.evidence(
            findings=[
                {
                    "id": "finding-1",
                    "summary": "A nonblocking improvement was deliberately deferred.",
                    "disposition": "deferred",
                    "rationale": "It is outside this ticket's acceptance boundary.",
                    "follow_up": "#999",
                }
            ],
            feedback_dispositions=[
                {
                    "kind": "pull-request-comment",
                    "id": "comment-1",
                    "body_digest": "sha256:"
                    + hashlib.sha256(
                        b"P3 deferred to a focused follow-up."
                    ).hexdigest(),
                    "disposition": "deferred",
                    "rationale": "Tracked by a focused follow-up.",
                    "follow_up": "#999",
                }
            ],
        )

        report = self.report(evidence=evidence)
        dispositions = {
            (item.kind, item.identifier): (item.disposition, item.body)
            for item in report.feedback
        }
        self.assertEqual(
            dispositions[("pull-request-comment", "comment-1")],
            ("deferred", "P3 deferred to a focused follow-up."),
        )
        self.assertEqual(
            dispositions[("review-thread", "thread-1")],
            ("resolved", "Deliberately deferred; the delivery remains clean."),
        )
        self.assertEqual(
            next(
                item.verdict
                for item in report.evidence
                if item.name == "unresolved-feedback-zero"
            ),
            "satisfied",
        )
        self.assertEqual(report.audit_evidence, evidence)
        self.assertTrue(report.acceptance_possible)

        edited = self.live_observation()
        edited["pull_request_comments"][0]["body"] += " Edited."
        self.write_observation(edited)
        stale = self.report(evidence=evidence)
        stale_verdicts = {item.name: item.verdict for item in stale.evidence}
        self.assertEqual(stale_verdicts["unresolved-feedback-zero"], "stale")
        self.assertFalse(stale.acceptance_possible)

    def test_live_base_ref_or_sha_drift_is_stale_and_cannot_be_accepted(self) -> None:
        original = self.live_observation()
        for field, value in (("ref", "refs/heads/other"), ("sha", "d" * 40)):
            with self.subTest(field=field):
                live = json.loads(json.dumps(original))
                live["pull_request"]["base"][field] = value
                self.write_observation(live)
                report = self.report()
                verdicts = {item.name: item.verdict for item in report.evidence}
                self.assertEqual(verdicts["independent-review-current"], "stale")
                self.assertEqual(verdicts["pull-request-mergeable"], "stale")
                self.assertFalse(report.acceptance_possible)
                before = self.mailbox_main()
                with self.assertRaisesRegex(
                    MailboxTransitionRejected,
                    "acceptance is blocked by current audit verdict stale",
                ):
                    self.accept(report)
                self.assertEqual(self.mailbox_main(), before)

    def test_required_check_configuration_is_identity_aware_and_fail_closed(self) -> None:
        original = self.live_observation()
        live = json.loads(json.dumps(original))
        live["required_checks"]["configuration_read"] = False
        self.write_observation(live)
        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(verdicts["required-checks-pass"], "unknown")

        live = json.loads(json.dumps(original))
        live["checks"] = [
            {
                "id": "optional-check",
                "pull_request_number": live["pull_request"]["number"],
                "kind": "CHECK_RUN",
                "name": "optional",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "candidate_sha": live["pull_request"]["head"]["sha"],
                "details_url": None,
            }
        ]
        self.write_observation(live)
        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(verdicts["required-checks-pass"], "satisfied")

        live["required_checks"]["contexts"] = [
            {"kind": "CHECK_RUN", "name": "required"}
        ]
        self.write_observation(live)
        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(verdicts["required-checks-pass"], "unknown")

        live["checks"].append(
            {
                "id": "required-check",
                "pull_request_number": live["pull_request"]["number"],
                "kind": "CHECK_RUN",
                "name": "required",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "candidate_sha": live["pull_request"]["head"]["sha"],
                "details_url": None,
            }
        )
        self.write_observation(live)
        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(verdicts["required-checks-pass"], "satisfied")

    def test_undispositioned_live_comment_blocks_acceptance(self) -> None:
        live = self.live_observation()
        live["pull_request_comments"] = [
            {
                "id": "comment-blocking",
                "author": "reviewer",
                "body": "This concern has no recorded disposition.",
                "created_at": live["observed_at"],
                "updated_at": live["observed_at"],
                "url": live["pull_request"]["url"] + "#issuecomment-blocking",
            }
        ]
        self.write_observation(live)
        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(verdicts["unresolved-feedback-zero"], "unknown")
        self.assertFalse(report.acceptance_possible)
        before = self.mailbox_main()
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "acceptance is blocked by current audit verdict unknown",
        ):
            self.accept(report)
        self.assertEqual(self.mailbox_main(), before)

    def test_acceptance_requires_a_second_provider_snapshot(self) -> None:
        report = self.report()
        before = self.mailbox_main()
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "current audit does not match the explicitly confirmed acceptance fence",
        ):
            self.accept(report, refresh_observation=False)
        self.assertEqual(self.mailbox_main(), before)

    def test_acceptance_without_test_clock_rejects_future_timestamp(self) -> None:
        report = self.report()
        boundary = datetime.fromisoformat(report.observed_at.replace("Z", "+00:00"))
        boundary += timedelta(seconds=1)
        with self.assertRaisesRegex(AuditError, "accepted_at cannot be in the future"):
            self.audit.accept(
                self.fixture.work_id,
                report.fence,
                confirmed=True,
                accepted_at=datetime.now(UTC) + timedelta(minutes=1),
                policy_target=self.fixture.policy_target(),
                host_target=self.fixture.delegation_host_target(),
                observation_path=self.fixture.observation_path,
                observation_not_before=boundary,
                audit_evidence=self.audit_evidence,
                now=None,
            )

    def test_later_head_drift_changes_audit_without_rewriting_acceptance(self) -> None:
        accepted = self.accept(self.report())
        original = self.current_work()["acceptance"]
        live = self.live_observation()
        live["pull_request"]["head"]["sha"] = "c" * 40
        for check in live["checks"]:
            check["candidate_sha"] = "c" * 40
        self.write_observation(live)

        report = self.report()
        verdicts = {item.name: item.verdict for item in report.evidence}
        self.assertEqual(report.acceptance_commit, accepted.commit)
        self.assertEqual(report.overall_verdict, "stale")
        self.assertEqual(verdicts["pull-request-head-current"], "stale")
        self.assertEqual(verdicts["pull-request-mergeable"], "stale")
        self.assertEqual(self.current_work()["acceptance"], original)


if __name__ == "__main__":
    unittest.main()
