"""Executable contract for project-serial claims and hash-bound checkpoints."""

from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any

from contract_tests import test_mailbox as fixtures
from contract_tests.test_planning import (
    AUTHORITY,
    EVIDENCE,
    OBSERVED_AT,
    git,
    observation,
    write_json,
)
from skills.atelier.scripts.claiming import (
    CheckpointRequest,
    ClaimCoordinator,
    ClaimFence,
    ClaimingError,
    HostTarget,
    _candidate_remote_reachable,
    new_identifier,
)
from skills.atelier.scripts.git_mailbox import MailboxTransitionRejected
from skills.atelier.scripts.mailbox import _read_yaml, reconstruct_mailbox
from skills.atelier.scripts.planning import (
    ApprovalEnvelope,
    AssignmentDraft,
    InitiativeDraft,
    Planner,
    PolicyTarget,
)

DIGEST = "sha256:" + "d" * 64
HEAD = "b" * 40
CLAIMING_SCRIPT = Path(__file__).parents[1] / "skills/atelier/scripts/claiming.py"


class ClaimingContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="atelier-claiming-test-")
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

        self.observation_path = self.root / "observation.json"
        write_json(self.observation_path, observation())
        self.work_id = fixtures.identifier("wrk", 778)
        self.initiative_id = fixtures.identifier("ini", 778)
        planner = Planner(str(self.mailbox_remote), "main")
        planner.create_draft(
            self.assignment(),
            initiative=self.initiative(),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )
        preview = planner.preview_approval(
            self.work_id,
            expected_revision=1,
            envelope=ApprovalEnvelope(AUTHORITY, EVIDENCE),
            policy_target=self.policy_target(),
            observation_path=self.observation_path,
            observation_not_before=OBSERVED_AT,
            now=OBSERVED_AT + timedelta(seconds=30),
        )
        self.live_at = OBSERVED_AT + timedelta(minutes=1)
        write_json(self.observation_path, self.fresh_observation())
        approved = planner.approve(
            preview,
            approved_by="operator",
            approved_at=self.live_at,
            policy_target=self.policy_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=self.live_at + timedelta(seconds=30),
        )
        self.approved_commit = approved.commit
        self.coordinator = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            candidate_verifier=lambda candidate: candidate["head_revision"] == HEAD,
            capability_verifier=lambda target: True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_policy(self, *, authority: tuple[str, ...] = AUTHORITY) -> None:
        fixtures.write_yaml(
            self.policy_path,
            {
                "schema": "atelier.project-policy/v1",
                "mailbox": {
                    "remote": str(self.mailbox_remote),
                    "realm_id": "personal",
                    "canonical_branch": "main",
                    "project_id": self.project_id,
                },
                "repository": {
                    "identity": self.repository,
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
                "authority": {"allow": list(authority)},
                "validation": {"required_commands": ["just test", "just lint"]},
                "acceptance": {"actor": "operator", "evidence": list(EVIDENCE)},
            },
        )

    def policy_target(self, checkout: Path | None = None) -> PolicyTarget:
        return PolicyTarget(
            checkout=checkout or self.project_checkout,
            remote="origin",
            canonical_ref="refs/heads/main",
            path=".atelier/policy.yaml",
        )

    def host_target(self) -> HostTarget:
        return HostTarget(
            descriptor_path=self.root / "host-capability.json",
            skill_name="agent-scripts:implement-ticket",
            skill_root=self.root / "agent-scripts",
            connector="github@openai-curated",
            operations=("read_issue",),
        )

    def fresh_observation(self) -> dict[str, Any]:
        value = observation()
        value["observed_at"] = self.live_at.isoformat().replace("+00:00", "Z")
        return value

    def assignment(self) -> AssignmentDraft:
        return AssignmentDraft(
            id=self.work_id,
            title="Claim one approved assignment",
            project_id=self.project_id,
            initiative_id=self.initiative_id,
            dependencies=(),
            replaces=(),
            ticket_number=777,
            ticket_url="https://github.com/example/project-1/issues/777",
            intent="Fence one current worker to one approved assignment.",
            rationale="Durable ownership must survive the worker transcript.",
            scope="Derive readiness, claim once, checkpoint mutations, and preserve handoffs.",
            non_goals="Do not implement or audit the linked ticket.",
            constraints="Use verified fast-forward Git mailbox writes.",
            edge_cases="Reject stale tokens, policy drift, ticket drift, and foreign claimants.",
            related_context="Delegation remains owned by the next graph ticket.",
            done_definition="One current claim and its exact checkpoint ledger reconstruct.",
            verification_expectations="Run focused and complete repository contract tests.",
            review_shape_guidance="Keep claim coordination independent from delegation.",
        )

    def initiative(self) -> InitiativeDraft:
        return InitiativeDraft(
            id=self.initiative_id,
            title="Accountable claim coordination",
            intent="Keep worker mutation ownership durable.",
            rationale="Host-local state cannot fence a fresh worker.",
            non_goals="Do not add a scheduler or lease service.",
            constraints="Keep the Git mailbox as the only shared state.",
            edge_cases="A worker may disappear with or without a candidate.",
            related_context="The assignment is project-specific.",
            outcome="One recoverable project-serial claim.",
        )

    def claim(
        self,
        *,
        coordinator: ClaimCoordinator | None = None,
        policy_target: PolicyTarget | None = None,
        claim_id: str | None = None,
        worker_run_id: str | None = None,
        token: str = "token-0",
    ):
        return (coordinator or self.coordinator).claim(
            self.work_id,
            claim_id=claim_id or new_identifier("clm"),
            worker_run_id=worker_run_id or new_identifier("run"),
            continuation_token=token,
            approved_commit=self.approved_commit,
            claimed_at=OBSERVED_AT + timedelta(minutes=1),
            policy_target=policy_target or self.policy_target(),
            host_target=self.host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=OBSERVED_AT + timedelta(minutes=1),
        )

    def fence(self, result) -> ClaimFence:
        return ClaimFence(
            claim_id=result.claim_id,
            worker_run_id=result.worker_run_id,
            sequence=result.sequence,
            continuation_token=result.continuation_token,
        )

    def checkpoint(
        self,
        result,
        *,
        action: str,
        token: str,
        candidate_head: str | None = None,
        phase: str = "pre_external_mutation",
        candidate: dict[str, Any] | None = None,
    ):
        return self.coordinator.authorize(
            self.work_id,
            CheckpointRequest(
                fence=self.fence(result),
                phase=phase,
                action=action,
                proposed_effect_digest=DIGEST,
                candidate_head=candidate_head,
                acknowledged_candidate_head=(
                    candidate_head if phase == "candidate_published" else None
                ),
                next_continuation_token=token,
                recorded_at=OBSERVED_AT + timedelta(minutes=2),
                candidate=candidate,
            ),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=OBSERVED_AT + timedelta(minutes=2),
        )

    def candidate(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "remote": "origin",
            "remote_url": "git@github.com:example/project-1.git",
            "remote_ref": "refs/heads/scott/example-work",
            "base_revision": "a" * 40,
            "head_revision": HEAD,
            "pull_request": None,
            "workspace_id": None,
            "published_at": "2026-07-28T04:02:00Z",
        }

    def publish_candidate_with_descendant(self):
        candidate_head = git(self.project_checkout, "rev-parse", "HEAD").stdout.strip()
        candidate_ref = "refs/heads/scott/example-work"
        git(self.project_checkout, "push", "origin", f"{candidate_head}:{candidate_ref}")
        candidate = self.candidate()
        candidate.update(remote_ref=candidate_ref, head_revision=candidate_head)
        self.coordinator = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            candidate_verifier=lambda value: _candidate_remote_reachable(
                {**value, "remote_url": str(self.project_remote)}
            ),
            capability_verifier=lambda target: True,
        )
        claimed = self.claim()
        push = self.checkpoint(
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate_head=candidate_head,
        )
        published = self.checkpoint(
            push,
            action="repository.candidate.push",
            token="token-2",
            candidate_head=candidate_head,
            phase="candidate_published",
            candidate=candidate,
        )
        candidate_marker = self.project_checkout / "candidate.txt"
        candidate_marker.write_text("descendant\n", encoding="utf-8")
        git(self.project_checkout, "add", str(candidate_marker))
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "advance candidate",
        )
        git(self.project_checkout, "push", "origin", f"HEAD:{candidate_ref}")
        return published, candidate_head

    def mailbox_clone(self, name: str) -> Path:
        checkout = self.root / name
        git(None, "clone", str(self.mailbox_remote), str(checkout))
        return checkout

    def test_concurrent_workers_produce_exactly_one_current_claim(self) -> None:
        policy_a = self.root / "policy-a"
        policy_b = self.root / "policy-b"
        git(None, "clone", str(self.project_remote), str(policy_a))
        git(None, "clone", str(self.project_remote), str(policy_b))
        results: list[object] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def attempt(number: int, checkout: Path) -> None:
            coordinator = ClaimCoordinator(
                str(self.mailbox_remote),
                "main",
                candidate_verifier=lambda candidate: True,
                capability_verifier=lambda target: True,
            )
            try:
                result = self.claim(
                    coordinator=coordinator,
                    policy_target=self.policy_target(checkout),
                    claim_id=fixtures.identifier("clm", 100 + number),
                    worker_run_id=fixtures.identifier("run", 100 + number),
                )
            except Exception as error:
                with lock:
                    errors.append(error)
            else:
                with lock:
                    results.append(result)

        threads = [
            threading.Thread(target=attempt, args=(1, policy_a)),
            threading.Thread(target=attempt, args=(2, policy_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MailboxTransitionRejected)
        snapshot = reconstruct_mailbox(self.mailbox_clone("claim-read"))
        self.assertEqual(snapshot["views"]["active"], [self.work_id])

    def test_checkpoint_rotates_token_and_rejects_replay_and_ticket_drift(self) -> None:
        claimed = self.claim()
        allowed = self.checkpoint(
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        self.assertEqual(allowed.sequence, 1)
        self.assertEqual(allowed.continuation_token, "token-1")

        with self.assertRaisesRegex(MailboxTransitionRejected, "stale or foreign"):
            self.checkpoint(
                claimed,
                action="repository.candidate.create",
                token="replayed-token",
            )

        changed = self.fresh_observation()
        changed["issue"]["body"] = "Materially changed after claim."
        write_json(self.observation_path, changed)
        with self.assertRaisesRegex(
            MailboxTransitionRejected, "material ticket observation changed"
        ):
            self.checkpoint(
                allowed,
                action="repository.candidate.create",
                token="token-2",
            )

    def test_candidate_publication_requires_paired_push_and_exact_remote_reachability(self) -> None:
        claimed = self.claim()
        push = self.checkpoint(
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate_head=HEAD,
        )
        published = self.checkpoint(
            push,
            action="repository.candidate.push",
            token="token-2",
            candidate_head=HEAD,
            phase="candidate_published",
            candidate=self.candidate(),
        )
        self.assertEqual(published.sequence, 2)

        checkout = self.mailbox_clone("candidate-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(work["claim"]["candidate"]["head_revision"], HEAD)
        self.assertEqual(
            [entry["phase"] for entry in work["claim"]["checkpoint"]["authorizations"]],
            ["pre_external_mutation", "candidate_published"],
        )

    def test_policy_tightening_denies_removed_action_without_widening_claim_authority(self) -> None:
        claimed = self.claim()
        self.write_policy(
            authority=tuple(action for action in AUTHORITY if action != "review.resolve")
        )
        git(self.project_checkout, "add", "-A")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "tighten project policy",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")

        with self.assertRaisesRegex(MailboxTransitionRejected, "exceeds effective authority"):
            self.checkpoint(
                claimed,
                action="review.resolve",
                token="token-1",
                candidate_head=HEAD,
            )

    def test_blocked_takeover_preserves_unresolved_blocker_and_candidate(self) -> None:
        published, _candidate_head = self.publish_candidate_with_descendant()
        blocker_id = new_identifier("msg")
        blocked = self.coordinator.block(
            self.work_id,
            self.fence(published),
            message_id=blocker_id,
            receipt_id=new_identifier("rcp"),
            subject="A planner decision is required",
            detail="The exact candidate is preserved while the worker waits.",
            created_at=OBSERVED_AT + timedelta(minutes=3),
        )
        self.assertEqual(blocked.status, "blocked")

        takeover_message_id = new_identifier("msg")
        takeover = self.coordinator.takeover(
            self.work_id,
            self.fence(blocked),
            claim_id=new_identifier("clm"),
            worker_run_id=new_identifier("run"),
            continuation_token="takeover-token-0",
            takeover_message_id=takeover_message_id,
            reason="The prior worker cannot continue; preserve its exact candidate.",
            taken_over_at=OBSERVED_AT + timedelta(minutes=4),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=OBSERVED_AT + timedelta(minutes=4),
        )
        self.assertEqual(takeover.status, "blocked")
        takeover_checkout = self.mailbox_clone("takeover-read")
        takeover_work, _ = _read_yaml(
            takeover_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        takeover_message, _ = _read_yaml(
            takeover_checkout / f"work/{self.work_id}/messages/{takeover_message_id}.md",
            frontmatter=True,
            label="takeover message",
        )
        self.assertEqual(takeover_work["blocking_message_id"], blocker_id)
        self.assertEqual(takeover_message["in_reply_to"], blocker_id)
        self.assertIsNone(takeover_message["resolves"])
        with self.assertRaisesRegex(MailboxTransitionRejected, "stale or foreign"):
            self.coordinator.release(
                self.work_id,
                self.fence(blocked),
                receipt_id=new_identifier("rcp"),
                reason="A stale worker must not release the replacement claim.",
                ended_at=OBSERVED_AT + timedelta(minutes=5),
            )

    def test_release_and_reclaim_accept_reachable_candidate_ancestor(self) -> None:
        published, candidate_head = self.publish_candidate_with_descendant()
        released = self.coordinator.release(
            self.work_id,
            self.fence(published),
            receipt_id=new_identifier("rcp"),
            reason="Return the exact transferable candidate to ready work.",
            ended_at=OBSERVED_AT + timedelta(minutes=5),
        )
        self.assertEqual(released.status, "approved")
        reclaimed = self.claim(token="reclaim-token-0")
        checkout = self.mailbox_clone("handoff-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(reclaimed.status, "active")
        self.assertEqual(work["claim"]["candidate"]["head_revision"], candidate_head)

    def test_missing_capability_and_wrong_approval_commit_fail_before_mailbox_write(self) -> None:
        before = git(
            None, "--git-dir", str(self.mailbox_remote), "rev-parse", "main"
        ).stdout.strip()
        wrong_approval = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            f"{self.approved_commit}^",
        ).stdout.strip()
        unavailable = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            capability_verifier=lambda target: False,
        )
        with self.assertRaisesRegex(ClaimingError, "capability is unavailable"):
            unavailable.claim(
                self.work_id,
                claim_id=new_identifier("clm"),
                worker_run_id=new_identifier("run"),
                continuation_token="token-0",
                approved_commit=self.approved_commit,
                claimed_at=OBSERVED_AT + timedelta(minutes=1),
                policy_target=self.policy_target(),
                host_target=self.host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                now=OBSERVED_AT + timedelta(minutes=1),
            )
        with self.assertRaisesRegex(MailboxTransitionRejected, "approved commit"):
            self.coordinator.claim(
                self.work_id,
                claim_id=new_identifier("clm"),
                worker_run_id=new_identifier("run"),
                continuation_token="token-0",
                approved_commit=wrong_approval,
                claimed_at=OBSERVED_AT + timedelta(minutes=1),
                policy_target=self.policy_target(),
                host_target=self.host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                now=OBSERVED_AT + timedelta(minutes=1),
            )
        after = git(None, "--git-dir", str(self.mailbox_remote), "rev-parse", "main").stdout.strip()
        self.assertEqual(after, before)

    def test_cli_generates_a_strict_durable_identifier(self) -> None:
        completed = subprocess.run(
            ["python3", str(CLAIMING_SCRIPT), "new-id", "clm"],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertRegex(
            completed.stdout.strip(),
            r"^clm_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )


if __name__ == "__main__":
    unittest.main()
