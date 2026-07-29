from __future__ import annotations

import json
import unittest
from datetime import timedelta

from contract_tests import test_claiming
from skills.atelier.scripts.audit import AuditCoordinator
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

    def report(self):
        return self.audit.audit(
            self.fixture.work_id,
            policy_target=self.fixture.policy_target(),
            host_target=self.fixture.delegation_host_target(),
            observation_path=self.fixture.observation_path,
            observation_not_before=self.observation_not_before,
            now=self.now,
        )

    def accept(self, report, *, confirmed: bool = True):
        return self.audit.accept(
            self.fixture.work_id,
            report.fence,
            confirmed=confirmed,
            accepted_at=self.now,
            policy_target=self.fixture.policy_target(),
            host_target=self.fixture.delegation_host_target(),
            observation_path=self.fixture.observation_path,
            observation_not_before=self.observation_not_before,
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
                for name in test_claiming.APPROVED_EVIDENCE
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
                for name in test_claiming.APPROVED_EVIDENCE
            },
        )
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

        report = self.report()
        dispositions = {
            (item.kind, item.identifier): (item.disposition, item.body)
            for item in report.feedback
        }
        self.assertEqual(
            dispositions[("pull-request-comment", "comment-1")],
            ("recorded", "P3 deferred to a focused follow-up."),
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
        self.assertTrue(report.acceptance_possible)

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
