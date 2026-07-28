"""Executable contract for one explicitly approved GitHub-backed assignment."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from contract_tests import test_mailbox as fixtures
from skills.atelier.scripts.git_mailbox import MailboxTransitionRejected, TransitionContext
from skills.atelier.scripts.mailbox import _read_yaml, reconstruct_mailbox
from skills.atelier.scripts.planning import (
    ApprovalEnvelope,
    AssignmentDraft,
    InitiativeDraft,
    Planner,
    PlanningError,
    PolicyTarget,
    new_identifier,
)

OBSERVED_AT = datetime(2026, 7, 28, 4, tzinfo=UTC)
AUTHORITY = (
    "repository.candidate.create",
    "repository.candidate.push",
    "pull_request.create",
    "pull_request.update",
    "review.reply",
    "review.resolve",
)
EVIDENCE = (
    "candidate-remote-reachable",
    "pull-request-head-current",
    "pull-request-open",
    "pull-request-mergeable",
    "required-checks-pass",
    "required-validation-reported",
    "independent-review-current",
    "unresolved-feedback-zero",
)


def git(cwd: Path | None, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def issue_reference(number: int, *, state: str = "OPEN") -> dict[str, object]:
    return {
        "id": f"issue-{number}",
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "url": f"https://github.com/example/project-1/issues/{number}",
    }


def observation(*, blocked: bool = False, with_pull_request: bool = False) -> dict[str, Any]:
    issue = issue_reference(777)
    issue.update(
        {
            "body": "Implement one complete planning assignment.",
            "updated_at": "2026-07-28T04:00:00Z",
            "parent": issue_reference(772),
            "sub_issues": [],
            "blocked_by": [issue_reference(776, state="OPEN" if blocked else "CLOSED")],
            "blocking": [issue_reference(778)],
        }
    )
    pull_request = None
    if with_pull_request:
        pull_request = {
            "id": "pull-request-900",
            "number": 900,
            "title": "Existing implementation",
            "body": "Refs #777",
            "url": "https://github.com/example/project-1/pull/900",
            "state": "OPEN",
            "is_draft": False,
            "merged": False,
            "mergeable": "MERGEABLE",
            "merge_state_status": "CLEAN",
            "review_decision": None,
            "base": {
                "repository": "example/project-1",
                "ref": "refs/heads/main",
                "sha": "a" * 40,
            },
            "head": {
                "repository": "example/project-1",
                "ref": "refs/heads/feature",
                "sha": "b" * 40,
            },
            "updated_at": "2026-07-28T04:00:00Z",
        }
    return {
        "schema": "atelier.github-observation/v1",
        "observed_at": "2026-07-28T04:00:00Z",
        "repository": {
            "id": "repository-project-1",
            "name_with_owner": "example/project-1",
            "url": "https://github.com/example/project-1",
        },
        "issue": issue,
        "issue_comments": [],
        "pull_request": pull_request,
        "pull_request_comments": [],
        "reviews": [],
        "checks": [],
        "threads": [],
        "completeness": {
            "issue": True,
            "issue_comments": True,
            "issue_relationships": True,
            "pull_request": True,
            "pull_request_comments": True,
            "reviews": True,
            "checks": True,
            "threads": True,
        },
    }


class PlanningContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="atelier-planning-test-")
        self.root = Path(self.temporary.name)
        self.mailbox_remote = self.root / "mailbox.git"
        git(None, "init", "--bare", "--initial-branch=main", str(self.mailbox_remote))
        mailbox_seed = self.root / "mailbox-seed"
        git(None, "clone", str(self.mailbox_remote), str(mailbox_seed))
        mailbox = fixtures.MailboxFixture(mailbox_seed)
        self.project_id, self.repository = mailbox.add_project(1)
        git(mailbox_seed, "add", "-A")
        git(
            mailbox_seed,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "seed mailbox",
        )
        git(mailbox_seed, "push", "origin", "HEAD:main")

        self.project_remote = self.root / "project.git"
        git(None, "init", "--bare", "--initial-branch=main", str(self.project_remote))
        self.project_checkout = self.root / "project"
        git(None, "clone", str(self.project_remote), str(self.project_checkout))
        self.policy_path = self.project_checkout / ".atelier/policy.yaml"
        self.policy_path.parent.mkdir(parents=True)
        self.write_policy()
        git(self.project_checkout, "add", "-A")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "add project policy",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")
        self.policy_commit = git(self.project_checkout, "rev-parse", "HEAD").stdout.strip()

        self.observation_path = self.root / "observation.json"
        write_json(self.observation_path, observation())
        self.work_id = fixtures.identifier("wrk", 777)
        self.initiative_id = fixtures.identifier("ini", 777)
        self.planner = Planner(str(self.mailbox_remote), "main")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_policy(
        self,
        *,
        repository: str | None = None,
        realm_id: str = "personal",
    ) -> None:
        value = {
            "schema": "atelier.project-policy/v1",
            "mailbox": {
                "remote": str(self.mailbox_remote),
                "realm_id": realm_id,
                "canonical_branch": "main",
                "project_id": self.project_id,
            },
            "repository": {
                "identity": repository or self.repository,
                "canonical_ref": "refs/heads/main",
            },
            "ticket": {
                "provider": "github",
                "allowed_states": ["open"],
                "require_no_blockers": True,
                "material_fields": ["body", "state", "relationships"],
            },
            "execution": {
                "capability": "agent-scripts.implement-ticket/delegated-execution/v1",
                "delivery_outcome": "ready_pr",
                "parallel_assignments": False,
            },
            "authority": {"allow": list(AUTHORITY)},
            "validation": {"required_commands": ["just test", "just lint"]},
            "acceptance": {"actor": "operator", "evidence": list(EVIDENCE)},
        }
        fixtures.write_yaml(self.policy_path, value)

    def assignment(self, *, intent: str = "Produce durable approved intent.") -> AssignmentDraft:
        return AssignmentDraft(
            id=self.work_id,
            title="Plan one assignment",
            project_id=self.project_id,
            initiative_id=self.initiative_id,
            dependencies=(),
            replaces=(),
            ticket_number=777,
            ticket_url="https://github.com/example/project-1/issues/777",
            intent=intent,
            rationale="A fresh worker needs a complete contract.",
            scope="Create, revise, preview, and explicitly promote one assignment.",
            non_goals="Do not claim work or implement the linked ticket.",
            constraints="Use the Git mailbox as the only shared state.",
            edge_cases="Reject stale tickets, policies, revisions, and previews.",
            related_context="The initiative may describe a cross-project outcome.",
            done_definition="The approved revision is independently understandable.",
            verification_expectations="Run the repository contract tests.",
            review_shape_guidance="Keep this as one human-shaped ready-PR change.",
        )

    def initiative(
        self,
        *,
        outcome: str = "Coordinate one accountable outcome.",
    ) -> InitiativeDraft:
        return InitiativeDraft(
            id=self.initiative_id,
            title="Accountable planning",
            intent="Preserve intent across planner and worker tasks.",
            rationale="Host transcripts are not durable coordination.",
            non_goals="Do not grant execution authority.",
            constraints="Assignments remain repository-specific.",
            edge_cases="A later project may join without changing approved work.",
            related_context="The first assignment belongs to example/project-1.",
            outcome=outcome,
        )

    def policy_target(self) -> PolicyTarget:
        return PolicyTarget(
            checkout=self.project_checkout,
            remote="origin",
            canonical_ref="refs/heads/main",
            path=".atelier/policy.yaml",
        )

    def envelope(self) -> ApprovalEnvelope:
        return ApprovalEnvelope(AUTHORITY, EVIDENCE)

    def mailbox_clone(self) -> Path:
        checkout = self.root / f"read-{new_identifier('wrk')}"
        git(None, "clone", str(self.mailbox_remote), str(checkout))
        return checkout

    def create(self) -> None:
        self.planner.create_draft(
            self.assignment(),
            initiative=self.initiative(),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )

    def preview(self):
        return self.planner.preview_approval(
            self.work_id,
            expected_revision=1,
            envelope=self.envelope(),
            policy_target=self.policy_target(),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )

    def refresh_observation_after_approval(self) -> datetime:
        approved_at = OBSERVED_AT + timedelta(minutes=1)
        refreshed = observation()
        refreshed["observed_at"] = "2026-07-28T04:01:00Z"
        write_json(self.observation_path, refreshed)
        return approved_at

    def test_create_publishes_one_non_executable_initiative_and_assignment(self) -> None:
        result = self.planner.create_draft(
            self.assignment(),
            initiative=self.initiative(),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )

        checkout = self.mailbox_clone()
        work, body = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
        )
        initiative, initiative_body = _read_yaml(
            checkout / f"initiatives/{self.initiative_id}/initiative.md",
            frontmatter=True,
        )
        snapshot = reconstruct_mailbox(checkout)
        self.assertEqual(result.commit, git(checkout, "rev-parse", "HEAD").stdout.strip())
        self.assertEqual(work["status"], "draft")
        self.assertEqual(work["revision"], 1)
        self.assertIsNone(work["approval"])
        self.assertIsNone(work["claim"])
        self.assertIn("## Verification Expectations", body)
        self.assertEqual(initiative["id"], self.initiative_id)
        self.assertIn("## Outcome", initiative_body)
        self.assertNotIn(self.work_id, snapshot["views"]["ready"])

    def test_revision_changes_exact_draft_and_keeps_it_non_executable(self) -> None:
        self.create()
        result = self.planner.revise_draft(
            self.assignment(intent="Revise the durable intent."),
            expected_revision=1,
            initiative=self.initiative(outcome="Revise the cross-project explanation."),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )

        checkout = self.mailbox_clone()
        work, body = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
        )
        self.assertEqual(result.revision, 2)
        self.assertEqual(work["revision"], 2)
        self.assertEqual(work["status"], "draft")
        self.assertIsNone(work["approval"])
        self.assertIn("Revise the durable intent.", body)

    def test_only_explicit_operator_confirmation_promotes_exact_preview(self) -> None:
        self.create()
        preview = self.preview()
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        with self.assertRaisesRegex(PlanningError, "explicit operator approval"):
            self.planner.approve(
                preview,
                approved_by="planner",
                approved_at=OBSERVED_AT + timedelta(minutes=1),
                policy_target=self.policy_target(),
                observation_path=self.observation_path,
                observation_not_before=OBSERVED_AT,
                now=OBSERVED_AT + timedelta(seconds=30),
            )
        self.assertEqual(
            before,
            git(None, "--git-dir", str(self.mailbox_remote), "rev-parse", "main").stdout.strip(),
        )

        approved_at = self.refresh_observation_after_approval()
        result = self.planner.approve(
            preview,
            approved_by="operator",
            approved_at=approved_at,
            policy_target=self.policy_target(),
            observation_path=self.observation_path,
            observation_not_before=approved_at,
            now=approved_at + timedelta(seconds=30),
        )
        checkout = self.mailbox_clone()
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
        )
        self.assertEqual(result.status, "approved")
        self.assertEqual(work["status"], "approved")
        self.assertEqual(work["approval"]["revision"], 1)
        self.assertEqual(work["approval"]["policy"]["commit"], self.policy_commit)
        self.assertEqual(work["approval"]["authority_ceiling"], list(AUTHORITY))
        self.assertEqual(
            work["approval"]["acceptance"]["required_evidence"],
            list(EVIDENCE),
        )
        self.assertIsNone(work["claim"])

    def test_promotion_rejects_stale_or_ineligible_ticket_state(self) -> None:
        self.create()
        preview = self.preview()
        stale = observation()
        stale["observed_at"] = "2026-07-28T03:00:00Z"
        write_json(self.observation_path, stale)
        with self.assertRaisesRegex(PlanningError, "live-read boundary"):
            self.planner.approve(
                preview,
                approved_by="operator",
                approved_at=OBSERVED_AT,
                policy_target=self.policy_target(),
                observation_path=self.observation_path,
                observation_not_before=OBSERVED_AT,
                now=OBSERVED_AT + timedelta(seconds=30),
            )

        write_json(self.observation_path, observation(blocked=True))
        with self.assertRaisesRegex(PlanningError, "unresolved blockers"):
            self.preview()

        write_json(self.observation_path, observation(with_pull_request=True))
        with self.assertRaisesRegex(PlanningError, "pull-request observation"):
            self.preview()

    def test_promotion_rejects_policy_and_draft_drift_after_preview(self) -> None:
        self.create()
        preview = self.preview()
        self.write_policy(repository="github:example/other")
        git(self.project_checkout, "add", "-A")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "change policy identity",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")
        approved_at = self.refresh_observation_after_approval()
        with self.assertRaisesRegex(PlanningError, "does not match project"):
            self.planner.approve(
                preview,
                approved_by="operator",
                approved_at=approved_at,
                policy_target=self.policy_target(),
                observation_path=self.observation_path,
                observation_not_before=approved_at,
                now=approved_at + timedelta(seconds=30),
            )

        git(self.project_checkout, "reset", "--hard", self.policy_commit)
        git(self.project_checkout, "push", "--force", "origin", "HEAD:main")
        self.planner.revise_draft(
            self.assignment(intent="A later unapproved revision."),
            expected_revision=1,
            initiative=self.initiative(),
            observation_path=self.observation_path,
            observation_not_before=approved_at,
            now=approved_at + timedelta(seconds=30),
        )
        with self.assertRaisesRegex(
            (PlanningError, MailboxTransitionRejected),
            "expected revision 1|previewed work",
        ):
            self.planner.approve(
                preview,
                approved_by="operator",
                approved_at=approved_at,
                policy_target=self.policy_target(),
                observation_path=self.observation_path,
                observation_not_before=approved_at,
                now=approved_at + timedelta(seconds=30),
            )

    def test_plan_time_reread_rejects_drift_after_revalidation(self) -> None:
        self.create()
        preview = self.preview()
        checkout = self.mailbox_clone()
        base_revision = git(checkout, "rev-parse", "HEAD").stdout.strip()
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        def mutate_observation() -> None:
            changed = observation()
            changed["issue"]["body"] = "Material body drift after revalidation."
            write_json(self.observation_path, changed)

        class InterleavingWriter:
            def publish(self, operation, *, revalidate, plan):
                context = TransitionContext(
                    checkout=checkout,
                    base_revision=base_revision,
                    snapshot=reconstruct_mailbox(checkout),
                    attempt=1,
                )
                revalidate(context)
                mutate_observation()
                plan(context)
                raise AssertionError(f"{operation}: drift was not rejected")

        planner = Planner(
            str(self.mailbox_remote),
            "main",
            writer=InterleavingWriter(),
        )
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "previewed work, policy, ticket, or authority changed",
        ):
            planner.approve(
                preview,
                approved_by="operator",
                approved_at=OBSERVED_AT,
                policy_target=self.policy_target(),
                observation_path=self.observation_path,
                observation_not_before=OBSERVED_AT,
                now=OBSERVED_AT + timedelta(seconds=30),
            )
        self.assertEqual(
            before,
            git(
                None,
                "--git-dir",
                str(self.mailbox_remote),
                "rev-parse",
                "main",
            ).stdout.strip(),
        )

    def test_preview_rejects_policy_from_another_mailbox_realm(self) -> None:
        self.create()
        self.write_policy(realm_id="other")
        git(self.project_checkout, "add", "-A")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "change policy realm",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")

        with self.assertRaisesRegex(
            PlanningError,
            "realm does not match the canonical mailbox",
        ):
            self.preview()

    def test_preview_digest_ignores_attribution_only_title_drift(self) -> None:
        self.create()
        first = self.preview()
        updated = copy.deepcopy(observation())
        updated["issue"]["title"] = "Renamed ticket"
        write_json(self.observation_path, updated)
        second = self.preview()
        self.assertEqual(first.preview_digest, second.preview_digest)

    def test_ids_are_uuidv7_and_invalid_or_incomplete_drafts_fail_closed(self) -> None:
        self.assertRegex(
            new_identifier("wrk"),
            r"^wrk_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        incomplete = self.assignment(intent=" ")
        with self.assertRaisesRegex(PlanningError, "assignment.intent"):
            self.planner.create_draft(
                incomplete,
                initiative=self.initiative(),
                observation_path=self.observation_path,
                observation_not_before=OBSERVED_AT,
                now=OBSERVED_AT + timedelta(seconds=30),
            )


if __name__ == "__main__":
    unittest.main()
