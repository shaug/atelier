"""Executable contract for project-serial claims and hash-bound checkpoints."""

from __future__ import annotations

import json
import subprocess
import sys
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
    AttemptEvidence,
    CheckpointRequest,
    ClaimCoordinator,
    ClaimFence,
    ClaimingError,
    HostTarget,
    _attempt_receipt,
    _candidate_remote_reachable,
    _policy_remote_matches_repository,
    _render_document,
    new_identifier,
)
from skills.atelier.scripts.delegation import (
    CAPABILITY,
    INVOCATION_SCHEMA,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    DelegationCoordinator,
    DelegationError,
    _require_tracker_transition,
)
from skills.atelier.scripts.git_mailbox import (
    FileChange,
    GitMailboxWriter,
    MailboxTransitionRejected,
    TransitionPlan,
    run_git,
)
from skills.atelier.scripts.mailbox import (
    MailboxValidationError,
    _read_yaml,
    reconstruct_mailbox,
)
from skills.atelier.scripts.planning import (
    ApprovalEnvelope,
    AssignmentDraft,
    InitiativeDraft,
    Planner,
    PolicyTarget,
)

APPROVED_EVIDENCE = EVIDENCE[:-1]
DIGEST = "sha256:" + "d" * 64
HEAD = "b" * 40
CLAIMING_SCRIPT = Path(__file__).parents[1] / "skills/atelier/scripts/claiming.py"
ROOT = Path(__file__).parents[1]
HOST_CAPABILITY = ROOT / "skills/atelier/references/host-capability.json"
INSTALLED_TICKET_SKILL = Path.home() / ".agents/skills/implement-ticket"
REQUIRED_HOST_OPERATIONS = (
    "github.issue.read",
    "github.issue.relationships.read",
    "github.pull-request.read",
    "github.pull-request.comments.read",
    "github.pull-request.reviews.read",
    "github.pull-request.checks.read",
    "github.repository.required-checks.read",
    "github.pull-request.threads.read",
)


class ProtocolFixture:
    def validate(self, kind: str, value: dict[str, Any]) -> list[str]:
        expected = {
            "invocation": INVOCATION_SCHEMA,
            "checkpoint-request": REQUEST_SCHEMA,
            "result": RESULT_SCHEMA,
        }
        return [] if value.get("schema") == expected[kind] else ["wrong protocol schema"]

    def validate_checkpoint_progress(
        self,
        last_sequence: int,
        current_token: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> list[str]:
        errors = []
        if request["sequence"] != last_sequence + 1:
            errors.append("sequence did not advance exactly once")
        if request["continuation_token"] != current_token:
            errors.append("continuation token is stale")
        if response["request_sequence"] != request["sequence"]:
            errors.append("response sequence mismatch")
        return errors

    def validate_checkpoint_exchange(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> list[str]:
        return [] if response["request_sequence"] == request["sequence"] else ["sequence mismatch"]

    def validate_result_checkpoint_state(
        self,
        invocation: dict[str, Any],
        result: dict[str, Any],
        last_sequence: int,
        current_token: str,
        observed_deployment,
        observed_tracker,
        consumed_authority: list[str],
    ) -> list[str]:
        errors = []
        if result["invocation_id"] != invocation["invocation_id"]:
            errors.append("result invocation mismatch")
        if result["checkpoint"] != {
            "last_sequence": last_sequence,
            "continuation_token": current_token,
        }:
            errors.append("result checkpoint mismatch")
        if set(result["authority_used"]) != set(consumed_authority):
            errors.append("result authority mismatch")
        return errors


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
        observation_script = self.root / "observe.py"
        observation_script.write_text(
            """import json
import sys
from datetime import UTC, datetime

path = sys.argv[1]
with open(path, encoding=\"utf-8\") as stream:
    value = json.load(stream)
value[\"observed_at\"] = datetime.now(UTC).isoformat().replace(\"+00:00\", \"Z\")
print(json.dumps(value, sort_keys=True))
""",
            encoding="utf-8",
        )
        self.observation_command = (sys.executable, str(observation_script), str(self.observation_path))
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
            envelope=ApprovalEnvelope(AUTHORITY, APPROVED_EVIDENCE),
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
            policy_remote_verifier=self.policy_remote_matches,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_policy(
        self,
        *,
        authority: tuple[str, ...] = AUTHORITY,
        evidence: tuple[str, ...] = APPROVED_EVIDENCE,
    ) -> None:
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
                    "capability": "agent-scripts.implement-ticket/delegated-execution/v2",
                    "delivery_outcome": "ready_pr",
                    "parallel_assignments": False,
                },
                "authority": {"allow": list(authority)},
                "validation": {"required_commands": ["just test", "just lint"]},
                "acceptance": {"actor": "operator", "evidence": list(evidence)},
            },
        )

    def commit_policy_change(
        self,
        *,
        authority: tuple[str, ...] = AUTHORITY,
        evidence: tuple[str, ...] = APPROVED_EVIDENCE,
    ) -> None:
        self.write_policy(authority=authority, evidence=evidence)
        git(self.project_checkout, "add", ".atelier/policy.yaml")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "change project policy",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")

    def policy_target(self, checkout: Path | None = None) -> PolicyTarget:
        return PolicyTarget(
            checkout=checkout or self.project_checkout,
            remote="origin",
            canonical_ref="refs/heads/main",
            path=".atelier/policy.yaml",
        )

    def policy_remote_matches(self, target: PolicyTarget, repository: str) -> bool:
        configured = run_git(target.checkout, ("remote", "get-url", target.remote))
        if configured.returncode != 0 or repository != self.repository:
            return False
        return Path(configured.stdout.strip()).resolve() == self.project_remote.resolve()

    def host_target(self) -> HostTarget:
        return HostTarget(
            descriptor_path=self.root / "host-capability.json",
            skill_name="agent-scripts:implement-ticket",
            skill_root=self.root / "agent-scripts",
            connector="github@openai-curated",
            operations=("read_issue",),
        )

    def delegation_host_target(self) -> HostTarget:
        return HostTarget(
            descriptor_path=self.root / "host-capability.json",
            skill_name="agent-scripts:implement-ticket",
            skill_root=self.root / "agent-scripts",
            connector="github@openai-curated",
            operations=("read_issue",),
        )

    def installed_host_target(self) -> HostTarget:
        return HostTarget(
            descriptor_path=HOST_CAPABILITY,
            skill_name="agent-scripts:implement-ticket",
            skill_root=INSTALLED_TICKET_SKILL,
            connector="github@openai-curated",
            operations=REQUIRED_HOST_OPERATIONS,
        )

    def assert_installed_result_valid_if_available(self, result: dict[str, Any]) -> None:
        if not (INSTALLED_TICKET_SKILL / "SKILL.md").is_file():
            return
        dependency = DelegationCoordinator(self.coordinator)._dependency(
            self.installed_host_target()
        )
        self.assertEqual(dependency.validate("result", result), [])

    def delegation(self) -> DelegationCoordinator:
        coordinator = DelegationCoordinator(self.coordinator)
        coordinator._dependency = lambda target: ProtocolFixture()
        return coordinator

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
        candidate_remote_ref: str | None = None,
        phase: str = "pre_external_mutation",
        candidate: dict[str, Any] | None = None,
        coordinator: ClaimCoordinator | None = None,
        host_target: HostTarget | None = None,
    ):
        if candidate_head is not None and candidate_remote_ref is None:
            candidate_remote_ref = (candidate or self.candidate())["remote_ref"]
        return (coordinator or self.coordinator).authorize(
            self.work_id,
            CheckpointRequest(
                fence=self.fence(result),
                phase=phase,
                action=action,
                proposed_effect_digest=DIGEST,
                candidate_head=candidate_head,
                candidate_remote_ref=candidate_remote_ref,
                acknowledged_candidate_head=(
                    candidate_head if phase == "candidate_published" else None
                ),
                next_continuation_token=token,
                recorded_at=OBSERVED_AT + timedelta(minutes=2),
                candidate=candidate,
            ),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=host_target or self.host_target(),
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

    def delegated_invocation(self, claimed):
        return self.delegation().prepare(
            self.work_id,
            self.fence(claimed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            checkpoint_invocation_path=self.root / "delegated-invocation.json",
            observation_command=self.observation_command,
            now=self.live_at + timedelta(seconds=30),
        )

    def delegated_request(
        self,
        invocation: dict[str, Any],
        prior,
        *,
        action: str,
        phase: str = "pre_external_mutation",
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "capability": CAPABILITY,
            "invocation_id": invocation["invocation_id"],
            "continuation_token": prior.continuation_token,
            "sequence": prior.sequence + 1,
            "phase": phase,
            "action": action,
            "ticket_observation": invocation["ticket"]["observation"],
            "candidate": candidate,
            "deployment": None,
            "proposed_effect": f"{action} candidate",
        }

    def delegated_checkpoint(
        self,
        delegation: DelegationCoordinator,
        invocation: dict[str, Any],
        prior,
        *,
        action: str,
        token: str,
        phase: str = "pre_external_mutation",
        candidate: dict[str, Any] | None = None,
    ):
        request = self.delegated_request(
            invocation,
            prior,
            action=action,
            phase=phase,
            candidate=candidate,
        )
        response = delegation.checkpoint(
            self.work_id,
            invocation,
            request,
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            recorded_at=self.live_at + timedelta(minutes=2),
            next_continuation_token=token,
            now=self.live_at + timedelta(minutes=2),
        )
        self.assertEqual(response["decision"], "allow", response)
        return type(prior)(
            operation="checkpoint",
            work_id=self.work_id,
            status="active",
            claim_id=prior.claim_id,
            worker_run_id=prior.worker_run_id,
            sequence=request["sequence"],
            continuation_token=response["continuation_token"],
            commit="0" * 40,
            base_revision="0" * 40,
            branch="main",
            attempts=1,
            recovered=False,
        )

    def assert_checkpoint_denied_without_mutation(
        self,
        delegation: DelegationCoordinator,
        invocation: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        response = delegation.checkpoint(
            self.work_id,
            invocation,
            request,
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            recorded_at=self.live_at + timedelta(minutes=2),
            next_continuation_token="must-not-be-used",
            now=self.live_at + timedelta(minutes=2),
        )
        after = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        self.assertEqual(response["decision"], "deny")
        self.assertEqual(response["continuation_token"], request["continuation_token"])
        self.assertEqual(after, before)
        return response

    def acceptance_records(self, invocation: dict[str, Any], candidate_head: str):
        return [
            {
                "criterion": item["criterion"],
                "required": item["required"],
                "evidence_category": item["evidence_category"],
                "stage": item["stage"],
                "candidate_sha": candidate_head,
                "deployed_sha": None,
                "environment": item["environment"],
                "url": item["url"],
                "source": item["source"],
                "status": "pass",
            }
            for item in invocation["acceptance_requirements"]
        ]

    def blocked_result(
        self,
        invocation: dict[str, Any],
        checkpointed,
        *,
        tracker_mode: str = "none",
        tracker_state: str = "open",
        reviews: list[dict[str, Any]] | None = None,
        candidate: dict[str, Any] | None = None,
        authority_used: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "capability": CAPABILITY,
            "invocation_id": invocation["invocation_id"],
            "terminal_state": "blocked",
            "ticket": invocation["ticket"],
            "repository": {
                "identity": invocation["repository"]["identity"],
                "base_ref": invocation["repository"]["base_ref"],
                "base_sha": invocation["repository"]["base_sha"],
            },
            "tracker_transition": {
                "provider": invocation["ticket"]["provider"],
                "ticket_id": invocation["ticket"]["id"],
                "mode": tracker_mode,
                "state": tracker_state,
                "observed_at": fixtures.TIMESTAMP,
            },
            "implementation_state": "published" if candidate else "local",
            "candidate": candidate,
            "handoff": {
                "transferable": candidate is not None,
                "reason": None if candidate else "No published candidate exists.",
            },
            "checkpoint": {
                "last_sequence": checkpointed.sequence,
                "continuation_token": checkpointed.continuation_token,
            },
            "validation": [],
            "reviews": reviews or [],
            "feedback": None,
            "authority_used": (
                authority_used
                if authority_used is not None
                else ["repository.candidate.create"]
            ),
            "acceptance_evidence": [
                {
                    "criterion": item["criterion"],
                    "required": item["required"],
                    "evidence_category": item["evidence_category"],
                    "stage": item["stage"],
                    "candidate_sha": candidate["head_sha"] if candidate else None,
                    "deployed_sha": None,
                    "environment": item["environment"],
                    "url": item["url"],
                    "source": None,
                    "status": "missing",
                }
                for item in invocation["acceptance_requirements"]
            ],
            "unresolved_obligations": ["Resolve the implementation blocker."],
            "blocking_reason": "The delegated worker could not publish a candidate.",
            "next_action": "Planner decides whether to retry or revise the work.",
        }

    def assert_blocked_ref_substitution_rejected(self, *, with_prior_candidate: bool) -> None:
        self.coordinator = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            candidate_verifier=lambda candidate: True,
            capability_verifier=lambda target: True,
            policy_remote_verifier=self.policy_remote_matches,
        )
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        prior = claimed
        if with_prior_candidate:
            acknowledged = {
                "repository": invocation["repository"]["identity"],
                "remote_url": invocation["repository"]["remote_url"],
                "remote_ref": "refs/heads/scott/acknowledged-candidate",
                "base_sha": invocation["repository"]["base_sha"],
                "head_sha": HEAD,
            }
            pushed = self.delegated_checkpoint(
                delegation,
                invocation,
                prior,
                action="repository.candidate.push",
                token="token-1",
                candidate=acknowledged,
            )
            prior = self.delegated_checkpoint(
                delegation,
                invocation,
                pushed,
                action="repository.candidate.push",
                token="token-2",
                phase="candidate_published",
                candidate=acknowledged,
            )
        authorized = {
            "repository": invocation["repository"]["identity"],
            "remote_url": invocation["repository"]["remote_url"],
            "remote_ref": "refs/heads/scott/authorized-push",
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": "c" * 40 if with_prior_candidate else HEAD,
        }
        pushed = self.delegated_checkpoint(
            delegation,
            invocation,
            prior,
            action="repository.candidate.push",
            token="token-3" if with_prior_candidate else "token-1",
            candidate=authorized,
        )
        substituted = {
            **authorized,
            "remote_ref": "refs/heads/scott/substituted-same-head",
            "publication": {"kind": "ordinary", "pull_requests": []},
        }
        result = self.blocked_result(
            invocation,
            pushed,
            candidate=substituted,
            authority_used=["repository.candidate.push"],
        )
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        with self.assertRaisesRegex(MailboxTransitionRejected, "exact push authorization"):
            delegation.finalize(
                self.work_id,
                invocation,
                result,
                self.fence(pushed),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.delegation_host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                ended_at=self.live_at + timedelta(minutes=3),
                now=self.live_at + timedelta(minutes=3),
            )

        after = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        self.assertEqual(after, before)

    def publish_candidate_with_descendant(self, *, with_pull_request: bool = False):
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
            policy_remote_verifier=self.policy_remote_matches,
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
        if with_pull_request:
            pull_request = self.checkpoint(
                published,
                action="pull_request.create",
                token="token-3",
                candidate_head=candidate_head,
            )
            republish = self.checkpoint(
                pull_request,
                action="repository.candidate.push",
                token="token-4",
                candidate_head=candidate_head,
            )
            candidate = dict(candidate)
            candidate["pull_request"] = "https://github.com/example/project-1/pull/778"
            published = self.checkpoint(
                republish,
                action="repository.candidate.push",
                token="token-5",
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

    def deliver_candidate(self, published, candidate_head: str) -> str:
        receipt_id = new_identifier("rcp")
        planned: dict[str, Any] = {}

        def revalidate(context) -> None:
            work, body = _read_yaml(
                context.checkout / f"work/{self.work_id}/work.md",
                frontmatter=True,
                label="work",
            )
            self.assertEqual(work["claim"]["id"], published.claim_id)
            receipt = _attempt_receipt(
                work,
                work["claim"],
                receipt_id=receipt_id,
                outcome="delivered",
                mutation_ownership="retained",
                ended_at=OBSERVED_AT + timedelta(minutes=4),
                evidence=AttemptEvidence(
                    validation=(
                        {
                            "command": "just test",
                            "outcome": "passed",
                            "candidate_revision": candidate_head,
                            "observed_at": fixtures.TIMESTAMP,
                        },
                    ),
                    reviews=(
                        {
                            "mechanism": "review-code-change",
                            "verdict": "clean",
                            "candidate_revision": candidate_head,
                            "comparison_base_revision": work["claim"]["candidate"]["base_revision"],
                            "observed_at": fixtures.TIMESTAMP,
                        },
                    ),
                ),
            )
            planned.clear()
            planned.update(work=work, body=body, receipt=receipt)

        def plan(context) -> TransitionPlan:
            work = dict(planned["work"])
            work["status"] = "delivered"
            work["attempt_receipt_id"] = receipt_id
            work["delivery_receipt_id"] = receipt_id
            return TransitionPlan(
                commit_message=f"deliver {self.work_id} for takeover contract",
                changes=(
                    FileChange(
                        f"work/{self.work_id}/receipts/{receipt_id}.md",
                        _render_document(planned["receipt"], "Delivered candidate."),
                    ),
                    FileChange(
                        f"work/{self.work_id}/work.md",
                        _render_document(work, planned["body"]),
                    ),
                ),
            )

        self.coordinator.writer.publish("deliver", revalidate=revalidate, plan=plan)
        return receipt_id

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
                policy_remote_verifier=self.policy_remote_matches,
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

    def _authorize_initial_pull_request(self):
        claimed = self.claim()
        initial_push = self.checkpoint(
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate_head=HEAD,
        )
        initial_publication = self.checkpoint(
            initial_push,
            action="repository.candidate.push",
            token="token-2",
            candidate_head=HEAD,
            phase="candidate_published",
            candidate=self.candidate(),
        )
        authority = self.checkpoint(
            initial_publication,
            action="pull_request.create",
            token="token-3",
            candidate_head=HEAD,
        )
        candidate = self.candidate()
        candidate["pull_request"] = "https://github.com/example/project-1/pull/1"
        return authority, candidate

    def test_candidate_publication_retains_pr_across_same_lineage_head_advance(self) -> None:
        self.coordinator.candidate_verifier = lambda candidate: True
        pull_request_authority, candidate_with_pull_request = (
            self._authorize_initial_pull_request()
        )
        repush = self.checkpoint(
            pull_request_authority,
            action="repository.candidate.push",
            token="token-4",
            candidate_head=HEAD,
        )
        published_pull_request = self.checkpoint(
            repush,
            action="repository.candidate.push",
            token="token-5",
            candidate_head=HEAD,
            phase="candidate_published",
            candidate=candidate_with_pull_request,
        )
        next_head = "d" * 40
        next_push = self.checkpoint(
            published_pull_request,
            action="repository.candidate.push",
            token="token-6",
            candidate_head=next_head,
        )
        next_candidate = candidate_with_pull_request.copy()
        next_candidate["head_revision"] = next_head

        published_next_head = self.checkpoint(
            next_push,
            action="repository.candidate.push",
            token="token-7",
            candidate_head=next_head,
            phase="candidate_published",
            candidate=next_candidate,
        )

        self.assertEqual(published_next_head.sequence, 7)
        checkout = self.mailbox_clone("retained-pr-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(work["claim"]["candidate"]["head_revision"], next_head)
        self.assertEqual(
            work["claim"]["candidate"]["pull_request"],
            candidate_with_pull_request["pull_request"],
        )

    def test_candidate_publication_rejects_pr_introduced_with_prior_head_authority(
        self,
    ) -> None:
        self.coordinator.candidate_verifier = lambda candidate: True
        pull_request_authority, candidate_with_pull_request = (
            self._authorize_initial_pull_request()
        )
        next_head = "d" * 40
        next_push = self.checkpoint(
            pull_request_authority,
            action="repository.candidate.push",
            token="token-4",
            candidate_head=next_head,
        )
        next_candidate = candidate_with_pull_request.copy()
        next_candidate["head_revision"] = next_head

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "candidate pull request metadata lacks exact pre-mutation authority",
        ):
            self.checkpoint(
                next_push,
                action="repository.candidate.push",
                token="token-5",
                candidate_head=next_head,
                phase="candidate_published",
                candidate=next_candidate,
            )

    def test_pull_request_url_change_consumes_fresh_mutation_authority(self) -> None:
        pull_request_authority, first_candidate = self._authorize_initial_pull_request()
        repush = self.checkpoint(
            pull_request_authority,
            action="repository.candidate.push",
            token="token-4",
            candidate_head=HEAD,
        )
        first_publication = self.checkpoint(
            repush,
            action="repository.candidate.push",
            token="token-5",
            candidate_head=HEAD,
            phase="candidate_published",
            candidate=first_candidate,
        )
        stale_push = self.checkpoint(
            first_publication,
            action="repository.candidate.push",
            token="token-6",
            candidate_head=HEAD,
        )
        replacement_candidate = first_candidate.copy()
        replacement_candidate["pull_request"] = "https://github.com/example/project-1/pull/999"

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "candidate pull request metadata lacks exact pre-mutation authority",
        ):
            self.checkpoint(
                stale_push,
                action="repository.candidate.push",
                token="stale-token-7",
                candidate_head=HEAD,
                phase="candidate_published",
                candidate=replacement_candidate,
            )

        fresh_authority = self.checkpoint(
            stale_push,
            action="pull_request.update",
            token="token-7",
            candidate_head=HEAD,
        )
        replacement_push = self.checkpoint(
            fresh_authority,
            action="repository.candidate.push",
            token="token-8",
            candidate_head=HEAD,
        )
        replacement_publication = self.checkpoint(
            replacement_push,
            action="repository.candidate.push",
            token="token-9",
            candidate_head=HEAD,
            phase="candidate_published",
            candidate=replacement_candidate,
        )

        self.assertEqual(replacement_publication.sequence, 9)
        checkout = self.mailbox_clone("replacement-pr-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(
            [
                entry["candidate_pull_request"]
                for entry in work["claim"]["checkpoint"]["authorizations"]
                if entry["phase"] == "candidate_published"
            ],
            [None, first_candidate["pull_request"], replacement_candidate["pull_request"]],
        )

    def test_default_policy_remote_verifier_binds_github_repository_identity(self) -> None:
        git(
            self.project_checkout,
            "remote",
            "set-url",
            "origin",
            "git@github.com:example/project-1.git",
        )
        target = self.policy_target()
        self.assertTrue(_policy_remote_matches_repository(target, self.repository))
        self.assertFalse(
            _policy_remote_matches_repository(target, "github:example/a-foreign-project")
        )
        git(self.project_checkout, "remote", "set-url", "origin", str(self.project_remote))

    def test_foreign_policy_mirror_cannot_hide_canonical_tightening(self) -> None:
        stale_remote = self.root / "stale-project.git"
        stale_checkout = self.root / "stale-project"
        git(None, "clone", "--bare", str(self.project_remote), str(stale_remote))
        git(None, "clone", str(stale_remote), str(stale_checkout))

        self.write_policy(
            authority=tuple(
                action for action in AUTHORITY if action != "repository.candidate.create"
            )
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
            "tighten canonical project policy",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "policy remote is foreign or unverifiable",
        ):
            self.claim(policy_target=self.policy_target(stale_checkout))

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

    def test_active_takeover_preserves_published_candidate_with_handoff_receipt(self) -> None:
        published, candidate_head = self.publish_candidate_with_descendant()
        prior_fence = self.fence(published)
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "active takeover requires a stable receipt identity",
        ):
            self.coordinator.takeover(
                self.work_id,
                prior_fence,
                claim_id=new_identifier("clm"),
                worker_run_id=new_identifier("run"),
                continuation_token="missing-active-takeover-receipt",
                takeover_message_id=new_identifier("msg"),
                reason="Candidate provenance cannot be implicit.",
                taken_over_at=OBSERVED_AT + timedelta(minutes=4),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                now=OBSERVED_AT + timedelta(minutes=4),
            )

        takeover_receipt_id = new_identifier("rcp")
        takeover = self.coordinator.takeover(
            self.work_id,
            prior_fence,
            claim_id=new_identifier("clm"),
            worker_run_id=new_identifier("run"),
            continuation_token="active-takeover-token-0",
            takeover_message_id=new_identifier("msg"),
            takeover_receipt_id=takeover_receipt_id,
            reason="The active worker disappeared after publishing its candidate.",
            taken_over_at=OBSERVED_AT + timedelta(minutes=4),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=OBSERVED_AT + timedelta(minutes=4),
        )
        checkout = self.mailbox_clone("active-takeover-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="active takeover work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{takeover_receipt_id}.md",
            frontmatter=True,
            label="active takeover handoff",
        )
        snapshot = reconstruct_mailbox(checkout)
        self.assertEqual(takeover.status, "active")
        self.assertEqual(work["attempt_receipt_id"], takeover_receipt_id)
        self.assertEqual(work["claim"]["checkpoint"]["sequence"], 0)
        self.assertEqual(work["claim"]["checkpoint"]["authorizations"], [])
        self.assertEqual(work["claim"]["candidate"]["head_revision"], candidate_head)
        self.assertEqual(receipt["claim_id"], prior_fence.claim_id)
        self.assertEqual(receipt["worker_run_id"], prior_fence.worker_run_id)
        self.assertEqual(receipt["candidate"]["head_revision"], candidate_head)
        self.assertEqual(receipt["outcome"], "released")
        self.assertEqual(receipt["mutation_ownership"], "relinquished")
        self.assertEqual(snapshot["views"]["active"], [self.work_id])

        with self.assertRaisesRegex(MailboxTransitionRejected, "stale or foreign"):
            self.coordinator.release(
                self.work_id,
                prior_fence,
                receipt_id=new_identifier("rcp"),
                reason="The fenced worker cannot release the replacement claim.",
                ended_at=OBSERVED_AT + timedelta(minutes=5),
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

        released = self.coordinator.release(
            self.work_id,
            self.fence(takeover),
            receipt_id=new_identifier("rcp"),
            reason="Relinquish the replacement claim while retaining the inherited decision.",
            ended_at=OBSERVED_AT + timedelta(minutes=5),
        )
        self.assertEqual(released.status, "approved")
        released_checkout = self.mailbox_clone("takeover-release-read")
        released_work, _ = _read_yaml(
            released_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="released takeover",
        )
        historical_blocker, _ = _read_yaml(
            released_checkout / f"work/{self.work_id}/messages/{blocker_id}.md",
            frontmatter=True,
            label="inherited historical blocker",
        )
        reconstruct_mailbox(released_checkout)
        self.assertEqual(released_work["status"], "approved")
        self.assertIsNone(released_work["blocking_message_id"])
        self.assertIsNone(historical_blocker["resolves"])

    def test_blocked_release_keeps_decision_historical_without_resolving_it(self) -> None:
        claimed = self.claim()
        blocker_id = new_identifier("msg")
        blocked = self.coordinator.block(
            self.work_id,
            self.fence(claimed),
            message_id=blocker_id,
            receipt_id=new_identifier("rcp"),
            subject="A planner decision is required",
            detail="Release must retain this unanswered decision as history.",
            created_at=OBSERVED_AT + timedelta(minutes=3),
        )
        release_receipt_id = new_identifier("rcp")
        released = self.coordinator.release(
            self.work_id,
            self.fence(blocked),
            receipt_id=release_receipt_id,
            reason="Relinquish the blocked attempt without inventing a resolution.",
            ended_at=OBSERVED_AT + timedelta(minutes=30),
        )
        self.assertEqual(released.status, "approved")
        reclaimed = self.claim(token="post-blocked-release-token")
        checkout = self.mailbox_clone("blocked-release-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        blocker, _ = _read_yaml(
            checkout / f"work/{self.work_id}/messages/{blocker_id}.md",
            frontmatter=True,
            label="historical blocker",
        )
        release_receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{release_receipt_id}.md",
            frontmatter=True,
            label="release receipt",
        )
        snapshot = reconstruct_mailbox(checkout)
        self.assertEqual(reclaimed.status, "active")
        self.assertEqual(work["status"], "active")
        self.assertIsNone(work["blocking_message_id"])
        self.assertEqual(work["attempt_receipt_id"], release_receipt_id)
        self.assertEqual(blocker["blocks"], "worker")
        self.assertIsNone(blocker["resolves"])
        self.assertEqual(release_receipt["outcome"], "released")
        self.assertEqual(snapshot["views"]["active"], [self.work_id])

        current_blocker_id = new_identifier("msg")
        reblocked = self.coordinator.block(
            self.work_id,
            self.fence(reclaimed),
            message_id=current_blocker_id,
            receipt_id=new_identifier("rcp"),
            subject="The replacement worker now needs a different decision",
            detail="A later attempt remains current regardless of attribution timestamps.",
            created_at=OBSERVED_AT + timedelta(minutes=5),
        )
        self.assertEqual(reblocked.status, "blocked")
        reblocked_checkout = self.mailbox_clone("reblocked-after-release-read")
        reblocked_work, _ = _read_yaml(
            reblocked_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="reblocked work",
        )
        reblocked_snapshot = reconstruct_mailbox(reblocked_checkout)
        self.assertEqual(reblocked_work["blocking_message_id"], current_blocker_id)
        self.assertEqual(reblocked_snapshot["views"]["blocked"], [self.work_id])

    def test_delivered_takeover_returns_active_with_historical_delivery(self) -> None:
        published, candidate_head = self.publish_candidate_with_descendant(with_pull_request=True)
        receipt_id = self.deliver_candidate(published, candidate_head)
        takeover = self.coordinator.takeover(
            self.work_id,
            self.fence(published),
            claim_id=new_identifier("clm"),
            worker_run_id=new_identifier("run"),
            continuation_token="delivered-takeover-token-0",
            takeover_message_id=new_identifier("msg"),
            reason="Continue from the delivered candidate under a replacement claim.",
            taken_over_at=OBSERVED_AT + timedelta(minutes=5),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            now=OBSERVED_AT + timedelta(minutes=5),
        )
        checkout = self.mailbox_clone("delivered-takeover-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{receipt_id}.md",
            frontmatter=True,
            label="delivery receipt",
        )
        snapshot = reconstruct_mailbox(checkout)
        self.assertEqual(takeover.status, "active")
        self.assertEqual(work["status"], "active")
        self.assertEqual(work["attempt_receipt_id"], receipt_id)
        self.assertIsNone(work["delivery_receipt_id"])
        self.assertEqual(receipt["candidate"]["head_revision"], candidate_head)
        self.assertEqual(snapshot["views"]["active"], [self.work_id])

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

    def test_checkpoint_capability_absence_and_retry_drift_fail_before_allowance(self) -> None:
        claimed = self.claim()
        unavailable = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            capability_verifier=lambda target: False,
            policy_remote_verifier=self.policy_remote_matches,
        )
        with self.assertRaisesRegex(ClaimingError, "capability is unavailable"):
            self.checkpoint(
                claimed,
                action="repository.candidate.push",
                token="missing-capability-token",
                candidate_head=HEAD,
                coordinator=unavailable,
            )

        message_id = new_identifier("msg")
        message = {
            "schema": "atelier.message/v1",
            "id": message_id,
            "work_id": self.work_id,
            "kind": "instruction",
            "author_role": "planner",
            "worker_run_id": None,
            "audience": "worker",
            "in_reply_to": None,
            "resolves": None,
            "blocks": None,
            "created_at": fixtures.TIMESTAMP,
            "subject": "Concurrent instruction",
        }
        concurrent_writer = GitMailboxWriter(str(self.mailbox_remote), "main")

        def advance() -> None:
            concurrent_writer.publish(
                "concurrent instruction",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    commit_message="append concurrent instruction",
                    changes=(
                        FileChange(
                            f"work/{self.work_id}/messages/{message_id}.md",
                            _render_document(message, "Revalidate before continuing."),
                        ),
                    ),
                ),
            )

        advance_pending = True

        def runner(cwd, arguments):
            nonlocal advance_pending
            if arguments and arguments[0] == "push" and advance_pending:
                advance_pending = False
                advance()
            return run_git(cwd, arguments)

        capability_checks = 0

        def capability_verifier(target) -> bool:
            nonlocal capability_checks
            capability_checks += 1
            return capability_checks == 1

        retrying = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            writer=GitMailboxWriter(str(self.mailbox_remote), "main", runner=runner),
            capability_verifier=capability_verifier,
            policy_remote_verifier=self.policy_remote_matches,
        )
        with self.assertRaisesRegex(ClaimingError, "capability is unavailable"):
            self.checkpoint(
                claimed,
                action="repository.candidate.push",
                token="drifted-capability-token",
                candidate_head=HEAD,
                coordinator=retrying,
            )
        checkout = self.mailbox_clone("capability-drift-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(capability_checks, 2)
        self.assertEqual(work["claim"]["checkpoint"]["sequence"], 0)

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
            policy_remote_verifier=self.policy_remote_matches,
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

    def test_delegation_uses_current_policy_acceptance_after_approval_tightens(self) -> None:
        self.write_policy(evidence=EVIDENCE)
        git(self.project_checkout, "add", ".atelier/policy.yaml")
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "tighten acceptance evidence",
        )
        git(self.project_checkout, "push", "origin", "HEAD:main")

        claimed = self.claim()
        invocation = self.delegated_invocation(claimed)

        self.assertEqual(
            [item["criterion"] for item in invocation["acceptance_requirements"]],
            list(EVIDENCE),
        )

    def test_delegation_rejects_tracker_mutation_for_ready_and_blocked_results(self) -> None:
        current = observation()
        for terminal in ("ready_pr", "blocked"):
            for transition in (
                {"provider": "github", "ticket_id": "777", "mode": "manual", "state": "open"},
                {
                    "provider": "github",
                    "ticket_id": "777",
                    "mode": "automatic",
                    "state": "closed",
                },
            ):
                with self.subTest(terminal=terminal, transition=transition):
                    result = {
                        "terminal_state": terminal,
                        "ticket": {"provider": "github"},
                        "tracker_transition": transition,
                    }
                    with self.assertRaisesRegex(MailboxTransitionRejected, "tracker transition"):
                        _require_tracker_transition(result, current)

    def test_delegation_prepares_v2_invocation_and_records_blocked_receipt(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = delegation.prepare(
            self.work_id,
            self.fence(claimed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            checkpoint_invocation_path=self.root / "delegated-invocation.json",
            observation_command=self.observation_command,
            now=self.live_at + timedelta(seconds=30),
        )
        self.assertEqual(invocation["schema"], INVOCATION_SCHEMA)
        self.assertEqual(invocation["capability"], CAPABILITY)
        self.assertEqual(invocation["ticket"]["observation"], self.fresh_observation_digest())
        self.assertEqual(
            invocation["accepted_terminal_states"], ["ready_pr", "blocked", "requires_epic"]
        )
        checkpointed = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        result = {
            "schema": RESULT_SCHEMA,
            "capability": CAPABILITY,
            "invocation_id": invocation["invocation_id"],
            "terminal_state": "blocked",
            "ticket": invocation["ticket"],
            "repository": {
                "identity": invocation["repository"]["identity"],
                "base_ref": invocation["repository"]["base_ref"],
                "base_sha": invocation["repository"]["base_sha"],
            },
            "tracker_transition": {
                "provider": "github",
                "ticket_id": invocation["ticket"]["id"],
                "mode": "none",
                "state": "open",
                "observed_at": fixtures.TIMESTAMP,
            },
            "implementation_state": "local",
            "candidate": None,
            "handoff": {"transferable": False, "reason": "No published candidate exists."},
            "checkpoint": {
                "last_sequence": checkpointed.sequence,
                "continuation_token": checkpointed.continuation_token,
            },
            "validation": [],
            "reviews": [],
            "feedback": None,
            "authority_used": ["repository.candidate.create"],
            "acceptance_evidence": [
                {
                    "criterion": item["criterion"],
                    "required": item["required"],
                    "evidence_category": item["evidence_category"],
                    "stage": item["stage"],
                    "candidate_sha": None,
                    "deployed_sha": None,
                    "environment": item["environment"],
                    "url": item["url"],
                    "source": None,
                    "status": "missing",
                }
                for item in invocation["acceptance_requirements"]
            ],
            "unresolved_obligations": ["Resolve the implementation blocker."],
            "blocking_reason": "The delegated worker could not publish a candidate.",
            "next_action": "Planner decides whether to retry or revise the work.",
        }
        delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(checkpointed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )
        checkout = self.mailbox_clone("delegated-blocked-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['attempt_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(work["status"], "blocked")
        self.assertEqual(receipt["outcome"], "blocked")
        self.assertEqual(receipt["unresolved_obligations"], result["unresolved_obligations"])
        reconstruct_mailbox(checkout)

    def test_delegation_accepts_v2_blocked_result_without_obligations(self) -> None:
        claimed = self.claim()
        fixture_delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        checkpointed = self.delegated_checkpoint(
            fixture_delegation,
            invocation,
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        result = self.blocked_result(invocation, checkpointed)
        result["unresolved_obligations"] = []
        self.assert_installed_result_valid_if_available(result)

        fixture_delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(checkpointed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        checkout = self.mailbox_clone("installed-v2-blocked-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, body = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['attempt_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(work["status"], "blocked")
        self.assertEqual(receipt["unresolved_obligations"], [])
        self.assertEqual(body, result["blocking_reason"])
        reconstruct_mailbox(checkout)

    def test_delegation_records_v2_requires_epic_result(self) -> None:
        claimed = self.claim()
        fixture_delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        result = self.blocked_result(invocation, claimed, authority_used=[])
        result.update(
            {
                "terminal_state": "requires_epic",
                "implementation_state": "none",
                "candidate": None,
                "handoff": {
                    "transferable": False,
                    "reason": "Whole epic requires implement-epic",
                },
                "unresolved_obligations": [],
                "blocking_reason": None,
                "next_action": "Return the work to the planner for epic decomposition.",
            }
        )
        self.assert_installed_result_valid_if_available(result)

        fixture_delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(claimed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        checkout = self.mailbox_clone("installed-v2-requires-epic-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, body = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['attempt_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(work["status"], "blocked")
        self.assertEqual(receipt["outcome"], "blocked")
        self.assertEqual(body, result["handoff"]["reason"])
        reconstruct_mailbox(checkout)

    def test_delegation_rejects_blocked_tracker_mutation_before_receipt(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        checkpointed = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        result = self.blocked_result(
            invocation, checkpointed, tracker_mode="manual", tracker_state="closed"
        )
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        with self.assertRaisesRegex(MailboxTransitionRejected, "tracker transition"):
            delegation.finalize(
                self.work_id,
                invocation,
                result,
                self.fence(checkpointed),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.delegation_host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                ended_at=self.live_at + timedelta(minutes=3),
                now=self.live_at + timedelta(minutes=3),
            )

        after = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        self.assertEqual(after, before)

    def test_delegation_rejects_altered_invocation_at_finalization(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        checkpointed = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        result = self.blocked_result(invocation, checkpointed)
        altered = {**invocation, "validation": ["just test"]}
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        with self.assertRaisesRegex(DelegationError, "sealed digest"):
            delegation.finalize(
                self.work_id,
                altered,
                result,
                self.fence(checkpointed),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.delegation_host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                ended_at=self.live_at + timedelta(minutes=3),
                now=self.live_at + timedelta(minutes=3),
            )

        after = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        self.assertEqual(after, before)

    def test_delegation_normalizes_unavailable_blocked_review(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        candidate = {
            "repository": invocation["repository"]["identity"],
            "remote_url": invocation["repository"]["remote_url"],
            "remote_ref": "refs/heads/scott/blocked-candidate",
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": HEAD,
        }
        created = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate=candidate,
        )
        published = self.delegated_checkpoint(
            delegation,
            invocation,
            created,
            action="repository.candidate.push",
            token="token-2",
            phase="candidate_published",
            candidate=candidate,
        )
        reviews = [
            {
                "name": "review-code-change",
                "outcome": "unavailable",
                "candidate_sha": HEAD,
                "observed_at": fixtures.TIMESTAMP,
            },
        ]
        terminal_candidate = {
            **candidate,
            "publication": {"kind": "ordinary", "pull_requests": []},
        }
        result = self.blocked_result(
            invocation,
            published,
            reviews=reviews,
            candidate=terminal_candidate,
            authority_used=["repository.candidate.push"],
        )
        delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(published),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        checkout = self.mailbox_clone("delegated-review-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['attempt_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(
            [review["verdict"] for review in receipt["reviews"]],
            ["blocked"],
        )
        self.assertEqual(receipt["reviews"][0]["mechanism"], "review-code-change")
        reconstruct_mailbox(checkout)

    def test_delegation_denies_stale_checkpoint_without_mailbox_mutation(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        request = self.delegated_request(invocation, claimed, action="repository.candidate.create")
        request["continuation_token"] = "stale-token"

        self.assert_checkpoint_denied_without_mutation(delegation, invocation, request)

    def test_delegation_denies_wrong_sequence_with_current_token_without_mutation(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        request = self.delegated_request(invocation, claimed, action="repository.candidate.create")
        request["sequence"] += 1

        self.assert_checkpoint_denied_without_mutation(delegation, invocation, request)

    def test_delegation_denies_altered_invocation_without_mutation(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        altered = {**invocation, "validation": ["just test"]}
        request = self.delegated_request(altered, claimed, action="repository.candidate.create")

        response = self.assert_checkpoint_denied_without_mutation(delegation, altered, request)
        self.assertIn("sealed digest", response["reason"])

    def test_delegation_denies_foreign_checkpoint_candidate_without_mutation(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        candidate = {
            "repository": invocation["repository"]["identity"],
            "remote_url": "https://github.com/foreign/project.git",
            "remote_ref": "refs/heads/scott/foreign-candidate",
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": HEAD,
        }
        request = self.delegated_request(
            invocation,
            claimed,
            action="repository.candidate.push",
            candidate=candidate,
        )

        response = self.assert_checkpoint_denied_without_mutation(delegation, invocation, request)
        self.assertIn("foreign", response["reason"])

    @unittest.skipUnless(
        (INSTALLED_TICKET_SKILL / "references/delegated-execution/validate.py").is_file(),
        "exact installed Agent Scripts v2 bundle is unavailable",
    )
    def test_checkpoint_command_services_one_request_with_installed_v2_bundle(self) -> None:
        claimed = self.claim()
        github_remote = "git@github.com:example/project-1.git"
        git(
            self.project_checkout,
            "config",
            f"url.{self.project_remote}.insteadOf",
            github_remote,
        )
        installed_policy_target = PolicyTarget(
            checkout=self.project_checkout,
            remote=github_remote,
            canonical_ref="refs/heads/main",
            path=".atelier/policy.yaml",
        )
        delegation = DelegationCoordinator(
            ClaimCoordinator(str(self.mailbox_remote), "main")
        )
        invocation = delegation.prepare(
            self.work_id,
            self.fence(claimed),
            approved_commit=self.approved_commit,
            policy_target=installed_policy_target,
            host_target=self.installed_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            checkpoint_invocation_path=self.root / "installed-delegated-invocation.json",
            observation_command=self.observation_command,
            now=self.live_at + timedelta(seconds=30),
        )
        request = self.delegated_request(
            invocation,
            claimed,
            action="repository.candidate.create",
        )

        completed = subprocess.run(
            invocation["checkpoint"]["command"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual(response["decision"], "allow", response)
        self.assertEqual(response["request_sequence"], 1)
        checkout = self.mailbox_clone("checkpoint-command-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(work["claim"]["checkpoint"]["sequence"], 1)

    def test_delegation_denies_checkpoint_after_current_policy_tightens(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        request = self.delegated_request(
            invocation,
            claimed,
            action="repository.candidate.create",
        )
        self.commit_policy_change(evidence=EVIDENCE)

        response = self.assert_checkpoint_denied_without_mutation(delegation, invocation, request)

        self.assertIn("stale", response["reason"])

    def test_delegation_rejects_terminal_result_after_current_policy_tightens(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        checkpointed = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.create",
            token="token-1",
        )
        result = self.blocked_result(invocation, checkpointed)
        self.commit_policy_change(evidence=EVIDENCE)
        before = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()

        with self.assertRaisesRegex(MailboxTransitionRejected, "stale"):
            delegation.finalize(
                self.work_id,
                invocation,
                result,
                self.fence(checkpointed),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.delegation_host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at,
                ended_at=self.live_at + timedelta(minutes=3),
                now=self.live_at + timedelta(minutes=3),
            )

        after = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        self.assertEqual(after, before)

    def test_blocked_result_rejects_same_head_on_unauthorized_ref_without_prior(self) -> None:
        self.assert_blocked_ref_substitution_rejected(with_prior_candidate=False)

    def test_blocked_result_rejects_same_head_on_unauthorized_ref_after_prior(self) -> None:
        self.assert_blocked_ref_substitution_rejected(with_prior_candidate=True)

    def test_blocked_result_recovers_unacknowledged_pushed_candidate(self) -> None:
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        candidate = {
            "repository": invocation["repository"]["identity"],
            "remote_url": invocation["repository"]["remote_url"],
            "remote_ref": "refs/heads/scott/recover-pushed-candidate",
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": HEAD,
        }
        pushed = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate=candidate,
        )
        terminal_candidate = {
            **candidate,
            "publication": {"kind": "ordinary", "pull_requests": []},
        }
        result = self.blocked_result(
            invocation,
            pushed,
            candidate=terminal_candidate,
            authority_used=["repository.candidate.push"],
        )

        delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(pushed),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        checkout = self.mailbox_clone("recovered-pushed-candidate-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['attempt_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(work["claim"]["candidate"]["head_revision"], HEAD)
        self.assertEqual(receipt["candidate"]["head_revision"], HEAD)
        reconstruct_mailbox(checkout)

    def test_blocked_result_replaces_older_candidate_with_latest_verified_push(self) -> None:
        self.coordinator = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            candidate_verifier=lambda candidate: True,
            capability_verifier=lambda target: True,
            policy_remote_verifier=self.policy_remote_matches,
        )
        claimed = self.claim()
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        old_candidate = {
            "repository": invocation["repository"]["identity"],
            "remote_url": invocation["repository"]["remote_url"],
            "remote_ref": "refs/heads/scott/older-candidate",
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": HEAD,
        }
        old_push = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate=old_candidate,
        )
        old_published = self.delegated_checkpoint(
            delegation,
            invocation,
            old_push,
            action="repository.candidate.push",
            token="token-2",
            phase="candidate_published",
            candidate=old_candidate,
        )
        latest_head = "c" * 40
        latest_candidate = {
            **old_candidate,
            "remote_ref": "refs/heads/scott/latest-candidate",
            "head_sha": latest_head,
        }
        latest_push = self.delegated_checkpoint(
            delegation,
            invocation,
            old_published,
            action="repository.candidate.push",
            token="token-3",
            candidate=latest_candidate,
        )
        result = self.blocked_result(
            invocation,
            latest_push,
            candidate={
                **latest_candidate,
                "publication": {"kind": "ordinary", "pull_requests": []},
            },
            authority_used=["repository.candidate.push"],
        )

        delegation.finalize(
            self.work_id,
            invocation,
            result,
            self.fence(latest_push),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        checkout = self.mailbox_clone("latest-pushed-candidate-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        self.assertEqual(work["claim"]["candidate"]["head_revision"], latest_head)
        reconstruct_mailbox(checkout)

    def test_inherited_candidate_survives_pr_block_release_reclaim_and_delivery(self) -> None:
        def fresh_coordinator() -> ClaimCoordinator:
            return ClaimCoordinator(
                str(self.mailbox_remote),
                "main",
                candidate_verifier=lambda value: _candidate_remote_reachable(
                    {**value, "remote_url": str(self.project_remote)}
                ),
                capability_verifier=lambda target: True,
                policy_remote_verifier=self.policy_remote_matches,
            )

        initial_claim = self.claim()
        self.coordinator = fresh_coordinator()
        initial_delegation = self.delegation()
        initial_invocation = self.delegated_invocation(initial_claim)
        candidate_head = git(self.project_checkout, "rev-parse", "HEAD").stdout.strip()
        candidate_ref = "refs/heads/scott/pr-recovery-candidate"
        git(self.project_checkout, "push", "origin", f"{candidate_head}:{candidate_ref}")
        candidate = {
            "repository": initial_invocation["repository"]["identity"],
            "remote_url": initial_invocation["repository"]["remote_url"],
            "remote_ref": candidate_ref,
            "base_sha": initial_invocation["repository"]["base_sha"],
            "head_sha": candidate_head,
        }
        initial_push = self.delegated_checkpoint(
            initial_delegation,
            initial_invocation,
            initial_claim,
            action="repository.candidate.push",
            token="initial-token-1",
            candidate=candidate,
        )
        published = self.delegated_checkpoint(
            initial_delegation,
            initial_invocation,
            initial_push,
            action="repository.candidate.push",
            token="initial-token-2",
            phase="candidate_published",
            candidate=candidate,
        )
        old_pull_request_url = "https://github.com/example/project-1/pull/793"
        old_terminal_candidate = {
            **candidate,
            "publication": {
                "kind": "ordinary",
                "pull_requests": [
                    {
                        "id": "793",
                        "url": old_pull_request_url,
                        "base_ref": initial_invocation["repository"]["base_ref"],
                        "base_sha": candidate["base_sha"],
                        "head_ref": candidate["remote_ref"],
                        "head_sha": candidate["head_sha"],
                        "state": "open",
                    }
                ],
            },
        }
        initial_pr_authorized = self.delegated_checkpoint(
            initial_delegation,
            initial_invocation,
            published,
            action="pull_request.create",
            token="initial-token-3",
            candidate=candidate,
        )
        initial_repush = self.delegated_checkpoint(
            initial_delegation,
            initial_invocation,
            initial_pr_authorized,
            action="repository.candidate.push",
            token="initial-token-4",
            candidate=candidate,
        )
        initial_pr_published = self.delegated_checkpoint(
            initial_delegation,
            initial_invocation,
            initial_repush,
            action="repository.candidate.push",
            token="initial-token-5",
            phase="candidate_published",
            candidate=old_terminal_candidate,
        )
        first_release_id = new_identifier("rcp")
        self.coordinator.release(
            self.work_id,
            self.fence(initial_pr_published),
            receipt_id=first_release_id,
            reason="Transfer the first PR-bearing candidate to a fresh worker.",
            ended_at=OBSERVED_AT + timedelta(minutes=6),
        )

        self.coordinator = fresh_coordinator()
        reclaimed = self.claim(token="pr-recovery-token-0")
        delegation = self.delegation()
        invocation = self.delegated_invocation(reclaimed)
        self.assertEqual(invocation["repository"]["base_sha"], candidate["base_sha"])
        pull_request_url = "https://github.com/example/project-1/pull/794"
        terminal_candidate = {
            **candidate,
            "publication": {
                "kind": "ordinary",
                "pull_requests": [
                    {
                        "id": "794",
                        "url": pull_request_url,
                        "base_ref": invocation["repository"]["base_ref"],
                        "base_sha": candidate["base_sha"],
                        "head_ref": candidate["remote_ref"],
                        "head_sha": candidate["head_sha"],
                        "state": "open",
                    }
                ],
            },
        }
        pr_authorized = self.delegated_checkpoint(
            delegation,
            invocation,
            reclaimed,
            action="pull_request.update",
            token="pr-recovery-token-1",
            candidate=candidate,
        )
        push_authorized = self.delegated_checkpoint(
            delegation,
            invocation,
            pr_authorized,
            action="repository.candidate.push",
            token="pr-recovery-token-2",
            candidate=candidate,
        )
        pr_acknowledged = self.delegated_checkpoint(
            delegation,
            invocation,
            push_authorized,
            action="repository.candidate.push",
            token="pr-recovery-token-3",
            phase="candidate_published",
            candidate=terminal_candidate,
        )
        blocked_result = self.blocked_result(
            invocation,
            pr_acknowledged,
            candidate=terminal_candidate,
            authority_used=["pull_request.update", "repository.candidate.push"],
        )
        blocked_result["blocking_reason"] = "A later planner decision is still required."
        delegation.finalize(
            self.work_id,
            invocation,
            blocked_result,
            self.fence(pr_acknowledged),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        blocked_checkout = self.mailbox_clone("pr-recovery-blocked-read")
        blocked_work, _ = _read_yaml(
            blocked_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="PR-bearing blocked work",
        )
        reconstruct_mailbox(blocked_checkout)
        self.assertEqual(blocked_work["claim"]["candidate"]["pull_request"], pull_request_url)

        release_id = new_identifier("rcp")
        self.coordinator.release(
            self.work_id,
            self.fence(pr_acknowledged),
            receipt_id=release_id,
            reason="Transfer the blocked PR-bearing candidate before a head advance.",
            ended_at=OBSERVED_AT + timedelta(minutes=6),
        )

        self.coordinator = fresh_coordinator()
        advanced_claim = self.claim(token="head-advance-token-0")
        advanced_delegation = self.delegation()
        advanced_invocation = self.delegated_invocation(advanced_claim)
        git(
            self.project_checkout,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "--allow-empty",
            "-m",
            "Advance inherited candidate",
        )
        advanced_head = git(self.project_checkout, "rev-parse", "HEAD").stdout.strip()
        git(self.project_checkout, "push", "origin", f"{advanced_head}:{candidate_ref}")
        advanced_candidate = {**candidate, "head_sha": advanced_head}
        advanced_terminal_candidate = {
            **advanced_candidate,
            "publication": {
                "kind": "ordinary",
                "pull_requests": [
                    {
                        "id": "794",
                        "url": pull_request_url,
                        "base_ref": advanced_invocation["repository"]["base_ref"],
                        "base_sha": advanced_candidate["base_sha"],
                        "head_ref": advanced_candidate["remote_ref"],
                        "head_sha": advanced_head,
                        "state": "open",
                    }
                ],
            },
        }
        advanced_push = self.delegated_checkpoint(
            advanced_delegation,
            advanced_invocation,
            advanced_claim,
            action="repository.candidate.push",
            token="head-advance-token-1",
            candidate=advanced_candidate,
        )
        advanced_published = self.delegated_checkpoint(
            advanced_delegation,
            advanced_invocation,
            advanced_push,
            action="repository.candidate.push",
            token="head-advance-token-2",
            phase="candidate_published",
            candidate=advanced_terminal_candidate,
        )
        advanced_blocked_result = self.blocked_result(
            advanced_invocation,
            advanced_published,
            candidate=advanced_terminal_candidate,
            authority_used=["repository.candidate.push"],
        )
        advanced_blocked_result["blocking_reason"] = (
            "The same pull request remains blocked after its candidate head advanced."
        )
        advanced_delegation.finalize(
            self.work_id,
            advanced_invocation,
            advanced_blocked_result,
            self.fence(advanced_published),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at,
            ended_at=self.live_at + timedelta(minutes=3),
            now=self.live_at + timedelta(minutes=3),
        )

        advanced_checkout = self.mailbox_clone("same-pr-advanced-head-blocked-read")
        advanced_work, _ = _read_yaml(
            advanced_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="same-PR advanced-head blocked work",
        )
        reconstruct_mailbox(advanced_checkout)
        self.assertEqual(
            advanced_work["claim"]["candidate"],
            {
                "repository": candidate["repository"],
                "remote": "origin",
                "remote_url": candidate["remote_url"],
                "remote_ref": candidate_ref,
                "base_revision": candidate["base_sha"],
                "head_revision": advanced_head,
                "pull_request": pull_request_url,
                "workspace_id": None,
                "published_at": (self.live_at + timedelta(minutes=2))
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )
        self.assertEqual(advanced_work["claim"]["inherited_receipt_id"], release_id)

        advanced_work["claim"]["inherited_receipt_id"] = first_release_id
        fixtures.write_markdown(
            advanced_checkout / f"work/{self.work_id}/work.md",
            advanced_work,
        )
        with self.assertRaisesRegex(MailboxValidationError, "checkpoint-pr-authority"):
            reconstruct_mailbox(advanced_checkout)

        advanced_release_id = new_identifier("rcp")
        self.coordinator.release(
            self.work_id,
            self.fence(advanced_published),
            receipt_id=advanced_release_id,
            reason="Transfer the same-PR advanced candidate to a final worker.",
            ended_at=OBSERVED_AT + timedelta(minutes=8),
        )
        self.coordinator = fresh_coordinator()
        final_claim = self.claim(token="ready-pr-token-0")
        final_delegation = self.delegation()
        final_invocation = self.delegated_invocation(final_claim)
        replacement_pull_request_url = "https://github.com/example/project-1/pull/795"
        replacement_terminal_candidate = json.loads(json.dumps(advanced_terminal_candidate))
        replacement_pull_request = replacement_terminal_candidate["publication"]["pull_requests"][0]
        replacement_pull_request["id"] = "795"
        replacement_pull_request["url"] = replacement_pull_request_url
        replacement_authorized = self.delegated_checkpoint(
            final_delegation,
            final_invocation,
            final_claim,
            action="pull_request.update",
            token="ready-pr-token-1",
            candidate=advanced_candidate,
        )

        live = observation(with_pull_request=True)
        live["observed_at"] = (
            (self.live_at + timedelta(minutes=9)).isoformat().replace("+00:00", "Z")
        )
        live["pull_request"]["url"] = replacement_pull_request_url
        live["pull_request"]["base"].update(
            ref=final_invocation["repository"]["base_ref"], sha=advanced_candidate["base_sha"]
        )
        live["pull_request"]["head"].update(
            ref=advanced_candidate["remote_ref"], sha=advanced_head
        )
        write_json(self.observation_path, live)
        ready_result = {
            "schema": RESULT_SCHEMA,
            "capability": CAPABILITY,
            "invocation_id": final_invocation["invocation_id"],
            "terminal_state": "ready_pr",
            "ticket": final_invocation["ticket"],
            "repository": {
                "identity": final_invocation["repository"]["identity"],
                "base_ref": final_invocation["repository"]["base_ref"],
                "base_sha": final_invocation["repository"]["base_sha"],
            },
            "tracker_transition": {
                "provider": final_invocation["ticket"]["provider"],
                "ticket_id": final_invocation["ticket"]["id"],
                "mode": "none",
                "state": "open",
                "observed_at": fixtures.TIMESTAMP,
            },
            "implementation_state": "published",
            "candidate": replacement_terminal_candidate,
            "handoff": {"transferable": True, "reason": None},
            "checkpoint": {
                "last_sequence": replacement_authorized.sequence,
                "continuation_token": replacement_authorized.continuation_token,
            },
            "validation": [
                {
                    "name": command,
                    "outcome": "passed",
                    "candidate_sha": advanced_head,
                    "observed_at": fixtures.TIMESTAMP,
                }
                for command in final_invocation["validation"]
            ],
            "reviews": [
                {
                    "name": "review-code-change",
                    "outcome": "passed",
                    "candidate_sha": advanced_head,
                    "observed_at": fixtures.TIMESTAMP,
                }
            ],
            "feedback": {
                "unresolved_material_count": 0,
                "candidate_sha": advanced_head,
                "observed_at": fixtures.TIMESTAMP,
            },
            "authority_used": ["pull_request.update"],
            "acceptance_evidence": self.acceptance_records(final_invocation, advanced_head),
            "unresolved_obligations": [],
            "blocking_reason": None,
            "next_action": "Atelier validates the inherited ready pull request.",
        }
        final_delegation.finalize(
            self.work_id,
            final_invocation,
            ready_result,
            self.fence(replacement_authorized),
            approved_commit=self.approved_commit,
            policy_target=self.policy_target(),
            host_target=self.delegation_host_target(),
            observation_path=self.observation_path,
            observation_not_before=self.live_at + timedelta(minutes=9),
            ended_at=self.live_at + timedelta(minutes=10),
            now=self.live_at + timedelta(minutes=10),
        )

        delivered_checkout = self.mailbox_clone("pr-recovery-delivered-read")
        delivered_work, _ = _read_yaml(
            delivered_checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="reclaimed delivered work",
        )
        reconstruct_mailbox(delivered_checkout)
        self.assertEqual(delivered_work["status"], "delivered")
        self.assertEqual(delivered_work["claim"]["candidate"]["head_revision"], advanced_head)
        self.assertEqual(
            delivered_work["claim"]["candidate"]["pull_request"],
            replacement_pull_request_url,
        )
        self.assertEqual(
            [
                (entry["phase"], entry["action"])
                for entry in delivered_work["claim"]["checkpoint"]["authorizations"]
            ],
            [("pre_external_mutation", "pull_request.update")],
        )

    def test_delegation_delivers_one_exact_ready_pull_request(self) -> None:
        claimed = self.claim()
        self.coordinator = ClaimCoordinator(
            str(self.mailbox_remote),
            "main",
            candidate_verifier=lambda value: _candidate_remote_reachable(
                {**value, "remote_url": str(self.project_remote)}
            ),
            capability_verifier=lambda target: True,
            policy_remote_verifier=self.policy_remote_matches,
        )
        delegation = self.delegation()
        invocation = self.delegated_invocation(claimed)
        candidate_head = git(self.project_checkout, "rev-parse", "HEAD").stdout.strip()
        candidate_ref = "refs/heads/scott/delegated-candidate"
        git(self.project_checkout, "push", "origin", f"{candidate_head}:{candidate_ref}")
        candidate = {
            "repository": self.repository,
            "remote_url": invocation["repository"]["remote_url"],
            "remote_ref": candidate_ref,
            "base_sha": invocation["repository"]["base_sha"],
            "head_sha": candidate_head,
        }
        push = self.delegated_checkpoint(
            delegation,
            invocation,
            claimed,
            action="repository.candidate.push",
            token="token-1",
            candidate=candidate,
        )
        published = self.delegated_checkpoint(
            delegation,
            invocation,
            push,
            action="repository.candidate.push",
            token="token-2",
            phase="candidate_published",
            candidate=candidate,
        )
        pull_request = self.delegated_checkpoint(
            delegation,
            invocation,
            published,
            action="pull_request.create",
            token="token-3",
            candidate=candidate,
        )
        pull_request_url = "https://github.com/example/project-1/pull/900"
        live = observation(with_pull_request=True)
        live["observed_at"] = (
            (self.live_at + timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        )
        live["pull_request"]["url"] = pull_request_url
        live["pull_request"]["base"].update(
            ref=invocation["repository"]["base_ref"],
            sha=invocation["repository"]["base_sha"],
        )
        live["pull_request"]["head"].update(ref=candidate_ref, sha=candidate_head)
        write_json(self.observation_path, live)
        result = {
            "schema": RESULT_SCHEMA,
            "capability": CAPABILITY,
            "invocation_id": invocation["invocation_id"],
            "terminal_state": "ready_pr",
            "ticket": invocation["ticket"],
            "repository": {
                "identity": invocation["repository"]["identity"],
                "base_ref": invocation["repository"]["base_ref"],
                "base_sha": invocation["repository"]["base_sha"],
            },
            "tracker_transition": {
                "provider": "github",
                "ticket_id": invocation["ticket"]["id"],
                "mode": "none",
                "state": "open",
                "observed_at": fixtures.TIMESTAMP,
            },
            "implementation_state": "published",
            "candidate": {
                **candidate,
                "publication": {
                    "kind": "ordinary",
                    "pull_requests": [
                        {
                            "id": "900",
                            "url": pull_request_url,
                            "base_ref": invocation["repository"]["base_ref"],
                            "base_sha": invocation["repository"]["base_sha"],
                            "head_ref": candidate_ref,
                            "head_sha": candidate_head,
                            "state": "open",
                        }
                    ],
                },
            },
            "handoff": {"transferable": True, "reason": None},
            "checkpoint": {
                "last_sequence": pull_request.sequence,
                "continuation_token": pull_request.continuation_token,
            },
            "validation": [
                {
                    "name": command,
                    "outcome": "passed",
                    "candidate_sha": candidate_head,
                    "observed_at": fixtures.TIMESTAMP,
                }
                for command in invocation["validation"]
            ],
            "reviews": [
                {
                    "name": "review-code-change",
                    "outcome": "passed",
                    "candidate_sha": candidate_head,
                    "observed_at": fixtures.TIMESTAMP,
                }
            ],
            "feedback": {
                "unresolved_material_count": 0,
                "candidate_sha": candidate_head,
                "observed_at": fixtures.TIMESTAMP,
            },
            "authority_used": ["repository.candidate.push", "pull_request.create"],
            "acceptance_evidence": self.acceptance_records(invocation, candidate_head),
            "unresolved_obligations": [],
            "blocking_reason": None,
            "next_action": "Atelier validates and presents the candidate for operator acceptance.",
        }
        def finalize(reported_result: dict[str, Any]) -> None:
            delegation.finalize(
                self.work_id,
                invocation,
                reported_result,
                self.fence(pull_request),
                approved_commit=self.approved_commit,
                policy_target=self.policy_target(),
                host_target=self.delegation_host_target(),
                observation_path=self.observation_path,
                observation_not_before=self.live_at + timedelta(minutes=3),
                ended_at=self.live_at + timedelta(minutes=4),
                now=self.live_at + timedelta(minutes=4),
            )

        before_rejection = git(
            None,
            "--git-dir",
            str(self.mailbox_remote),
            "rev-parse",
            "main",
        ).stdout.strip()
        for pr_field, live_section, live_field, substituted in (
            ("head_ref", "head", "ref", "refs/heads/substituted"),
            ("head_sha", "head", "sha", "c" * 40),
            ("base_sha", "base", "sha", "d" * 40),
        ):
            substituted_result = json.loads(json.dumps(result))
            substituted_live = json.loads(json.dumps(live))
            reported_pr = substituted_result["candidate"]["publication"]["pull_requests"][0]
            reported_pr[pr_field] = substituted
            substituted_live["pull_request"][live_section][live_field] = substituted
            write_json(self.observation_path, substituted_live)
            with self.assertRaisesRegex(
                MailboxTransitionRejected,
                "terminal pull request does not identify the acknowledged candidate",
            ):
                finalize(substituted_result)
            self.assertEqual(
                git(
                    None,
                    "--git-dir",
                    str(self.mailbox_remote),
                    "rev-parse",
                    "main",
                ).stdout.strip(),
                before_rejection,
            )
        foreign_head = json.loads(json.dumps(live))
        foreign_head["pull_request"]["head"]["repository"] = "foreign/fork"
        write_json(self.observation_path, foreign_head)
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "live pull request identity is not the terminal candidate",
        ):
            finalize(result)
        self.assertEqual(
            git(
                None,
                "--git-dir",
                str(self.mailbox_remote),
                "rev-parse",
                "main",
            ).stdout.strip(),
            before_rejection,
        )
        write_json(self.observation_path, live)

        foreign_review = json.loads(json.dumps(result))
        foreign_review["reviews"][0]["name"] = "generic-review"
        self.assert_installed_result_valid_if_available(foreign_review)
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "review evidence uses a mechanism Atelier cannot represent",
        ):
            finalize(foreign_review)
        self.assertEqual(
            git(
                None,
                "--git-dir",
                str(self.mailbox_remote),
                "rev-parse",
                "main",
            ).stdout.strip(),
            before_rejection,
        )

        finalize(result)
        checkout = self.mailbox_clone("delegated-delivered-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        receipt, _ = _read_yaml(
            checkout / f"work/{self.work_id}/receipts/{work['delivery_receipt_id']}.md",
            frontmatter=True,
            label="receipt",
        )
        self.assertEqual(work["status"], "delivered")
        self.assertEqual(work["claim"]["candidate"]["pull_request"], pull_request_url)
        self.assertEqual(receipt["candidate"], work["claim"]["candidate"])
        reconstruct_mailbox(checkout)

    def fresh_observation_digest(self) -> str:
        checkout = self.mailbox_clone("delegated-digest-read")
        work, _ = _read_yaml(
            checkout / f"work/{self.work_id}/work.md",
            frontmatter=True,
            label="work",
        )
        return work["claim"]["ticket_observation_digest"] if work["claim"] else ""

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
