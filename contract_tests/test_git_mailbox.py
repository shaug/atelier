"""Executable contract for verified fast-forward Git mailbox writes."""

from __future__ import annotations

import copy
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from contract_tests import test_mailbox as fixtures
from skills.atelier.scripts.git_mailbox import (
    FileChange,
    GitMailboxWriter,
    MailboxPersistenceUnknown,
    MailboxRemoteUnavailable,
    MailboxTransitionRejected,
    PendingWrite,
    TransitionContext,
    TransitionPlan,
    run_git,
)
from skills.atelier.scripts.mailbox import MailboxValidationError


def git(cwd: Path | None, *arguments: str) -> subprocess.CompletedProcess[str]:
    result = run_git(cwd, arguments)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


def markdown(value: dict[str, Any], body: str = "Fixture.\n") -> str:
    return f"---\n{fixtures.yaml_text(value)}---\n{body}"


def read_markdown(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    value = yaml.safe_load(frontmatter)
    if not isinstance(value, dict):
        raise AssertionError("fixture frontmatter is not a mapping")
    return value


def planner_message(work_id: str, number: int) -> tuple[str, str]:
    message_id = fixtures.identifier("msg", number)
    value = {
        "schema": "atelier.message/v1",
        "id": message_id,
        "work_id": work_id,
        "kind": "instruction",
        "author_role": "planner",
        "worker_run_id": None,
        "audience": "worker",
        "in_reply_to": None,
        "resolves": None,
        "blocks": None,
        "created_at": fixtures.TIMESTAMP,
        "subject": f"Instruction {number}",
    }
    return (
        f"work/{work_id}/messages/{message_id}.md",
        markdown(value),
    )


class LostPushResponse:
    """Let one push succeed, then hide its response and immediate read-back."""

    def __init__(self):
        self.hide_push = True
        self.hide_fetch = False

    def __call__(
        self,
        cwd: Path | None,
        arguments: tuple[str, ...] | list[str],
    ) -> subprocess.CompletedProcess[str]:
        result = run_git(cwd, arguments)
        if arguments and arguments[0] == "push" and self.hide_push and result.returncode == 0:
            self.hide_push = False
            self.hide_fetch = True
            return subprocess.CompletedProcess(
                ["git", *arguments],
                1,
                result.stdout,
                "simulated lost push response",
            )
        if arguments and arguments[0] == "fetch" and self.hide_fetch:
            self.hide_fetch = False
            return subprocess.CompletedProcess(
                ["git", *arguments],
                1,
                "",
                "simulated read-back outage",
            )
        return result


class TimeoutAfterSuccessfulPush:
    """Raise a real timeout after one push has reached the remote."""

    def __init__(self):
        self.timeout_push = True

    def __call__(
        self,
        cwd: Path | None,
        arguments: tuple[str, ...] | list[str],
    ) -> subprocess.CompletedProcess[str]:
        result = run_git(cwd, arguments)
        if arguments and arguments[0] == "push" and self.timeout_push and result.returncode == 0:
            self.timeout_push = False
            raise subprocess.TimeoutExpired(["git", *arguments], timeout=1)
        return result


class FetchTimeout:
    """Raise a real timeout at the first canonical fetch."""

    def __call__(
        self,
        cwd: Path | None,
        arguments: tuple[str, ...] | list[str],
    ) -> subprocess.CompletedProcess[str]:
        if arguments and arguments[0] == "fetch":
            raise subprocess.TimeoutExpired(["git", *arguments], timeout=1)
        return run_git(cwd, arguments)


class AdvanceBeforeFirstPush:
    """Run one concurrent transition before allowing a stale push to continue."""

    def __init__(self, advance: Callable[[], None]):
        self._advance = advance
        self.advance = True

    def __call__(
        self,
        cwd: Path | None,
        arguments: tuple[str, ...] | list[str],
    ) -> subprocess.CompletedProcess[str]:
        if arguments and arguments[0] == "push" and self.advance:
            self.advance = False
            self._advance()
        return run_git(cwd, arguments)


class GitMailboxWriteContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="atelier-git-write-test-")
        self.root = Path(self.temporary.name)
        self.remote = self.root / "mailbox.git"
        git(None, "init", "--bare", "--initial-branch=main", str(self.remote))
        seed = self.root / "seed"
        git(None, "clone", str(self.remote), str(seed))
        mailbox = fixtures.MailboxFixture(seed)
        self.work_id = mailbox.add_work(1, "approved")
        self.repository = mailbox.projects[mailbox.works[self.work_id]["project_id"]][
            "repository"
        ]
        git(seed, "add", "-A")
        git(
            seed,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "seed valid mailbox",
        )
        git(seed, "push", "origin", "HEAD:main")
        self.seed_revision = git(seed, "rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def writer(self, **kwargs: Any) -> GitMailboxWriter:
        return GitMailboxWriter(str(self.remote), "main", **kwargs)

    def remote_head(self) -> str:
        return git(None, "--git-dir", str(self.remote), "rev-parse", "main").stdout.strip()

    def test_one_transition_is_committed_and_read_back_exactly(self) -> None:
        path, content = planner_message(self.work_id, 1)
        result = self.writer().publish(
            "append instruction",
            revalidate=lambda context: None,
            plan=lambda context: TransitionPlan(
                "append instruction",
                (FileChange(path, content),),
            ),
        )

        self.assertEqual(result.base_revision, self.seed_revision)
        self.assertEqual(result.commit, self.remote_head())
        self.assertEqual(result.attempts, 1)
        self.assertFalse(result.recovered)
        shown = git(None, "--git-dir", str(self.remote), "show", f"{result.commit}:{path}")
        self.assertEqual(shown.stdout, content)
        parent_count = git(
            None,
            "--git-dir",
            str(self.remote),
            "rev-list",
            "--count",
            f"{self.seed_revision}..{result.commit}",
        )
        self.assertEqual(parent_count.stdout.strip(), "1")

    def test_concurrent_independent_messages_are_each_published_once(self) -> None:
        barrier = threading.Barrier(2)
        outcomes: list[Any] = []

        def publish(number: int) -> None:
            path, content = planner_message(self.work_id, number)

            def revalidate(context: TransitionContext) -> None:
                if context.attempt == 1:
                    barrier.wait(timeout=5)

            try:
                outcomes.append(
                    self.writer().publish(
                        f"append instruction {number}",
                        revalidate=revalidate,
                        plan=lambda context: TransitionPlan(
                            f"append instruction {number}",
                            (FileChange(path, content),),
                        ),
                    )
                )
            except Exception as error:  # pragma: no cover - assertion reports the exception
                outcomes.append(error)

        threads = [threading.Thread(target=publish, args=(number,)) for number in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(not isinstance(outcome, Exception) for outcome in outcomes), outcomes)
        self.assertEqual(sorted(outcome.attempts for outcome in outcomes), [1, 2])
        listing = git(
            None,
            "--git-dir",
            str(self.remote),
            "ls-tree",
            "-r",
            "--name-only",
            "main",
            f"work/{self.work_id}/messages",
        ).stdout.splitlines()
        self.assertEqual(len(listing), 2)
        self.assertEqual(len(set(listing)), 2)

    def test_concurrent_claims_have_exactly_one_winner(self) -> None:
        barrier = threading.Barrier(2)
        outcomes: list[Any] = []

        def publish(number: int) -> None:
            def revalidate(context: TransitionContext) -> None:
                work = read_markdown(context.checkout / f"work/{self.work_id}/work.md")
                if work["status"] != "approved" or work["claim"] is not None:
                    raise MailboxTransitionRejected("claim already exists")
                if context.attempt == 1:
                    barrier.wait(timeout=5)

            def plan(context: TransitionContext) -> TransitionPlan:
                work = read_markdown(context.checkout / f"work/{self.work_id}/work.md")
                work["status"] = "active"
                work["claim"] = fixtures.claim(
                    self.repository,
                    number,
                    with_candidate=False,
                )
                return TransitionPlan(
                    f"claim work {number}",
                    (FileChange(f"work/{self.work_id}/work.md", markdown(work)),),
                )

            try:
                outcomes.append(
                    self.writer().publish(
                        f"claim work {number}",
                        revalidate=revalidate,
                        plan=plan,
                    )
                )
            except Exception as error:
                outcomes.append(error)

        threads = [threading.Thread(target=publish, args=(number,)) for number in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        winners = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        losers = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual(len(losers), 1, outcomes)
        self.assertIsInstance(losers[0], MailboxTransitionRejected)
        fresh = self.root / "fresh-claim"
        git(None, "clone", str(self.remote), str(fresh))
        snapshot = fixtures.MAILBOX.reconstruct_mailbox(fresh)
        self.assertEqual(snapshot["views"]["active"], [self.work_id])

    def test_atomic_multi_document_transition_is_valid_in_a_fresh_clone(self) -> None:
        claim_result = self._claim()
        blocker_id = fixtures.identifier("msg", 9)
        receipt_id = fixtures.identifier("rcp", 9)

        def revalidate(context: TransitionContext) -> None:
            work = read_markdown(context.checkout / f"work/{self.work_id}/work.md")
            if work["claim"]["id"] != claim_result["id"]:
                raise MailboxTransitionRejected("claim changed")

        def plan(context: TransitionContext) -> TransitionPlan:
            work_path = f"work/{self.work_id}/work.md"
            work = read_markdown(context.checkout / work_path)
            work["status"] = "blocked"
            work["blocking_message_id"] = blocker_id
            work["attempt_receipt_id"] = receipt_id
            message = {
                "schema": "atelier.message/v1",
                "id": blocker_id,
                "work_id": self.work_id,
                "kind": "needs-decision",
                "author_role": "worker",
                "worker_run_id": work["claim"]["worker_run_id"],
                "audience": "planner",
                "in_reply_to": None,
                "resolves": None,
                "blocks": "worker",
                "created_at": fixtures.TIMESTAMP,
                "subject": "Choose the bounded behavior",
            }
            receipt = fixtures.receipt(
                work,
                self.repository,
                1,
                outcome="blocked",
                with_candidate=False,
            )
            receipt["id"] = receipt_id
            return TransitionPlan(
                "block work atomically",
                (
                    FileChange(work_path, markdown(work)),
                    FileChange(
                        f"work/{self.work_id}/messages/{blocker_id}.md",
                        markdown(message),
                    ),
                    FileChange(
                        f"work/{self.work_id}/receipts/{receipt_id}.md",
                        markdown(receipt),
                    ),
                ),
            )

        result = self.writer().publish(
            "block work",
            revalidate=revalidate,
            plan=plan,
        )
        fresh = self.root / "fresh-blocked"
        git(None, "clone", str(self.remote), str(fresh))
        snapshot = fixtures.MAILBOX.reconstruct_mailbox(fresh)
        self.assertEqual(snapshot["views"]["blocked"], [self.work_id])
        changed = git(
            None,
            "--git-dir",
            str(self.remote),
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            result.commit,
        ).stdout.splitlines()
        self.assertEqual(len(changed), 3)

    def test_ambiguous_push_recovers_after_later_commit_without_duplication(self) -> None:
        path, content = planner_message(self.work_id, 1)
        writer = self.writer(runner=LostPushResponse())
        with self.assertRaises(MailboxPersistenceUnknown) as raised:
            writer.publish(
                "append ambiguous instruction",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    "append ambiguous instruction",
                    (FileChange(path, content),),
                ),
            )
        pending = raised.exception.pending

        later_path, later_content = planner_message(self.work_id, 2)
        self.writer().publish(
            "append later instruction",
            revalidate=lambda context: None,
            plan=lambda context: TransitionPlan(
                "append later instruction",
                (FileChange(later_path, later_content),),
            ),
        )
        recovered = self.writer().recover(pending)

        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.recovered)
        history = git(
            None,
            "--git-dir",
            str(self.remote),
            "rev-list",
            "--all",
            "--",
            path,
        ).stdout.splitlines()
        self.assertEqual(history, [pending.commit])
        current = git(None, "--git-dir", str(self.remote), "rev-parse", "main").stdout.strip()
        ancestor = run_git(
            None,
            (
                "--git-dir",
                str(self.remote),
                "merge-base",
                "--is-ancestor",
                pending.commit,
                current,
            ),
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_timeout_after_success_enters_exact_read_back_recovery(self) -> None:
        path, content = planner_message(self.work_id, 1)
        result = self.writer(runner=TimeoutAfterSuccessfulPush()).publish(
            "append timed-out instruction",
            revalidate=lambda context: None,
            plan=lambda context: TransitionPlan(
                "append timed-out instruction",
                (FileChange(path, content),),
            ),
        )

        self.assertTrue(result.recovered)
        self.assertEqual(result.commit, self.remote_head())
        shown = git(None, "--git-dir", str(self.remote), "show", f"{result.commit}:{path}")
        self.assertEqual(shown.stdout, content)

    def test_fetch_timeout_fails_as_unavailable_current_state(self) -> None:
        with self.assertRaises(MailboxRemoteUnavailable):
            self.writer(runner=FetchTimeout()).publish(
                "unavailable fetch",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    "unavailable fetch",
                    (FileChange("atelier.yaml", "unreachable"),),
                ),
            )
        self.assertEqual(self.remote_head(), self.seed_revision)

    def test_absent_ambiguous_commit_recovers_as_safely_retryable(self) -> None:
        path, content = planner_message(self.work_id, 1)
        pending = PendingWrite(
            operation="append absent instruction",
            branch="main",
            commit="f" * 40,
            base_revision=self.seed_revision,
            changes=(FileChange(path, content),),
        )

        self.assertIsNone(self.writer().recover(pending))
        self.assertEqual(self.remote_head(), self.seed_revision)

    def test_unavailable_remote_never_reports_shared_success(self) -> None:
        missing = self.root / "missing.git"
        writer = GitMailboxWriter(str(missing), "main")
        with self.assertRaises(MailboxRemoteUnavailable):
            writer.publish(
                "unavailable transition",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    "unavailable transition",
                    (FileChange("atelier.yaml", "unreachable"),),
                ),
            )
        self.assertEqual(self.remote_head(), self.seed_revision)

    def test_deleted_canonical_ref_is_not_recreated_after_fetch(self) -> None:
        path, content = planner_message(self.work_id, 1)

        def delete_canonical_ref() -> None:
            git(
                None,
                "--git-dir",
                str(self.remote),
                "update-ref",
                "-d",
                "refs/heads/main",
            )

        with self.assertRaises(MailboxPersistenceUnknown):
            self.writer(runner=AdvanceBeforeFirstPush(delete_canonical_ref)).publish(
                "append after deleted canonical ref",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    "append after deleted canonical ref",
                    (FileChange(path, content),),
                ),
            )
        missing = run_git(
            None,
            ("--git-dir", str(self.remote), "rev-parse", "--verify", "refs/heads/main"),
        )
        self.assertNotEqual(missing.returncode, 0)

    def test_rewound_canonical_ref_fails_closed_after_fetch(self) -> None:
        self._append_instruction(1)
        fetched_head = self.remote_head()
        revalidations = 0

        def rewind_canonical_ref() -> None:
            git(
                None,
                "--git-dir",
                str(self.remote),
                "update-ref",
                "refs/heads/main",
                self.seed_revision,
                fetched_head,
            )

        def revalidate(context: TransitionContext) -> None:
            nonlocal revalidations
            revalidations += 1

        path, content = planner_message(self.work_id, 2)
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "moved backwards or diverged",
        ):
            self.writer(runner=AdvanceBeforeFirstPush(rewind_canonical_ref)).publish(
                "append after canonical rewind",
                revalidate=revalidate,
                plan=lambda context: TransitionPlan(
                    "append after canonical rewind",
                    (FileChange(path, content),),
                ),
            )
        self.assertEqual(revalidations, 1)
        self.assertEqual(self.remote_head(), self.seed_revision)

    def test_external_preconditions_are_reread_after_concurrent_update(self) -> None:
        observation = {"ticket": "approved"}
        attempts: list[int] = []
        path, content = planner_message(self.work_id, 1)

        def advance() -> None:
            observation["ticket"] = "changed"
            self._append_instruction(99)

        def revalidate(context: TransitionContext) -> None:
            attempts.append(context.attempt)
            if observation["ticket"] != "approved":
                raise MailboxTransitionRejected("material ticket observation changed")

        writer = self.writer(runner=AdvanceBeforeFirstPush(advance))
        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "material ticket observation changed",
        ):
            writer.publish(
                "append instruction under approved ticket",
                revalidate=revalidate,
                plan=lambda context: TransitionPlan(
                    "append instruction under approved ticket",
                    (FileChange(path, content),),
                ),
            )

        self.assertEqual(attempts, [1, 2])
        target = run_git(
            None,
            (
                "--git-dir",
                str(self.remote),
                "show",
                f"main:{path}",
            ),
        )
        self.assertNotEqual(target.returncode, 0)
        concurrent_path, _ = planner_message(self.work_id, 99)
        concurrent = git(
            None,
            "--git-dir",
            str(self.remote),
            "show",
            f"main:{concurrent_path}",
        )
        self.assertTrue(concurrent.stdout)

    def test_takeover_fences_the_prior_claimant_after_contention(self) -> None:
        old_claim = self._claim()
        new_claim = fixtures.claim(self.repository, 2, with_candidate=False)
        work_path = f"work/{self.work_id}/work.md"

        def take_over() -> None:
            def plan(context: TransitionContext) -> TransitionPlan:
                work = read_markdown(context.checkout / work_path)
                work["claim"] = copy.deepcopy(new_claim)
                return TransitionPlan(
                    "take over active work",
                    (FileChange(work_path, markdown(work)),),
                )

            self.writer().publish(
                "take over active work",
                revalidate=lambda context: None,
                plan=plan,
            )

        def revalidate(context: TransitionContext) -> None:
            claim = read_markdown(context.checkout / work_path)["claim"]
            if (
                claim["id"] != old_claim["id"]
                or claim["checkpoint"]["sequence"] != 0
                or claim["checkpoint"]["continuation_token"]
                != old_claim["checkpoint"]["continuation_token"]
            ):
                raise MailboxTransitionRejected("prior claim is fenced")

        def authorize(context: TransitionContext) -> TransitionPlan:
            work = read_markdown(context.checkout / work_path)
            checkpoint = work["claim"]["checkpoint"]
            checkpoint["sequence"] = 1
            checkpoint["continuation_token"] = "rotated-token"
            checkpoint["authorizations"].append(
                {
                    "sequence": 1,
                    "invocation_id": old_claim["worker_run_id"],
                    "phase": "pre_external_mutation",
                    "action": "repository.candidate.create",
                    "proposed_effect_digest": fixtures.DIGEST,
                    "candidate_head": None,
                    "acknowledged_candidate_head": None,
                    "recorded_at": fixtures.TIMESTAMP,
                }
            )
            return TransitionPlan(
                "authorize stale claimant",
                (FileChange(work_path, markdown(work)),),
            )

        with self.assertRaisesRegex(MailboxTransitionRejected, "prior claim is fenced"):
            self.writer(runner=AdvanceBeforeFirstPush(take_over)).publish(
                "authorize stale claimant",
                revalidate=revalidate,
                plan=authorize,
            )

        fresh = self.root / "fresh-takeover"
        git(None, "clone", str(self.remote), str(fresh))
        current = read_markdown(fresh / work_path)
        self.assertEqual(current["claim"]["id"], new_claim["id"])
        self.assertEqual(current["claim"]["checkpoint"]["authorizations"], [])

    def test_release_and_takeover_preserve_candidate_handoff(self) -> None:
        original_claim = self._claim(with_candidate=True)
        candidate = copy.deepcopy(original_claim["candidate"])
        work_path = f"work/{self.work_id}/work.md"
        receipt_id = fixtures.identifier("rcp", 1)

        def release(context: TransitionContext) -> TransitionPlan:
            work = read_markdown(context.checkout / work_path)
            released = fixtures.receipt(
                work,
                self.repository,
                1,
                outcome="released",
                with_candidate=True,
            )
            released["mutation_ownership"] = "relinquished"
            work["status"] = "approved"
            work["claim"] = None
            work["attempt_receipt_id"] = receipt_id
            return TransitionPlan(
                "release candidate handoff",
                (
                    FileChange(work_path, markdown(work)),
                    FileChange(
                        f"work/{self.work_id}/receipts/{receipt_id}.md",
                        markdown(released),
                    ),
                ),
            )

        self.writer().publish(
            "release candidate handoff",
            revalidate=lambda context: None,
            plan=release,
        )

        adopted_claim = fixtures.claim(self.repository, 2, with_candidate=False)
        adopted_claim["candidate"] = copy.deepcopy(candidate)

        def adopt(context: TransitionContext) -> TransitionPlan:
            work = read_markdown(context.checkout / work_path)
            receipt = read_markdown(
                context.checkout / f"work/{self.work_id}/receipts/{receipt_id}.md"
            )
            if receipt["candidate"] != candidate:
                raise MailboxTransitionRejected("released candidate changed")
            work["status"] = "active"
            work["claim"] = copy.deepcopy(adopted_claim)
            return TransitionPlan(
                "adopt released candidate",
                (FileChange(work_path, markdown(work)),),
            )

        self.writer().publish(
            "adopt released candidate",
            revalidate=lambda context: None,
            plan=adopt,
        )

        takeover_claim = fixtures.claim(self.repository, 3, with_candidate=False)
        takeover_claim["candidate"] = copy.deepcopy(candidate)

        def take_over(context: TransitionContext) -> TransitionPlan:
            work = read_markdown(context.checkout / work_path)
            work["claim"] = copy.deepcopy(takeover_claim)
            return TransitionPlan(
                "take over candidate handoff",
                (FileChange(work_path, markdown(work)),),
            )

        self.writer().publish(
            "take over candidate handoff",
            revalidate=lambda context: None,
            plan=take_over,
        )

        fresh = self.root / "fresh-handoff"
        git(None, "clone", str(self.remote), str(fresh))
        current = read_markdown(fresh / work_path)
        released = read_markdown(
            fresh / f"work/{self.work_id}/receipts/{receipt_id}.md"
        )
        self.assertEqual(released["candidate"], candidate)
        self.assertEqual(current["attempt_receipt_id"], receipt_id)
        self.assertEqual(current["claim"]["candidate"], candidate)
        self.assertEqual(current["claim"]["id"], takeover_claim["id"])
        fixtures.MAILBOX.reconstruct_mailbox(fresh)

    def test_policy_tightening_after_contention_does_not_widen_authority(self) -> None:
        approved = {"repository.candidate.push"}
        current = set(approved)
        effective_observations: list[set[str]] = []
        path, content = planner_message(self.work_id, 1)

        def advance() -> None:
            current.clear()
            current.update({"pull_request.create", "pull_request.merge"})
            self._append_instruction(99)

        def revalidate(context: TransitionContext) -> None:
            effective = approved & current
            effective_observations.append(effective)
            if "pull_request.merge" in effective:
                raise AssertionError("looser current policy widened approved authority")
            if "repository.candidate.push" not in effective:
                raise MailboxTransitionRejected("current policy removed candidate push")

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "current policy removed candidate push",
        ):
            self.writer(runner=AdvanceBeforeFirstPush(advance)).publish(
                "publish under effective authority",
                revalidate=revalidate,
                plan=lambda context: TransitionPlan(
                    "publish under effective authority",
                    (FileChange(path, content),),
                ),
            )
        self.assertEqual(effective_observations, [approved, set()])

    def test_pull_request_head_drift_blocks_retry_after_contention(self) -> None:
        delivered_head = fixtures.SHA_A
        live = {"head": delivered_head}
        path, content = planner_message(self.work_id, 1)

        def advance() -> None:
            live["head"] = fixtures.SHA_B
            self._append_instruction(99)

        def revalidate(context: TransitionContext) -> None:
            if live["head"] != delivered_head:
                raise MailboxTransitionRejected("pull request head changed")

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "pull request head changed",
        ):
            self.writer(runner=AdvanceBeforeFirstPush(advance)).publish(
                "publish against delivered head",
                revalidate=revalidate,
                plan=lambda context: TransitionPlan(
                    "publish against delivered head",
                    (FileChange(path, content),),
                ),
            )

    def test_invalid_transition_fails_closed_before_push(self) -> None:
        path = f"work/{fixtures.identifier('wrk', 9)}/work.md"
        before = self.remote_head()
        with self.assertRaises(MailboxValidationError):
            self.writer().publish(
                "publish unsupported schema",
                revalidate=lambda context: None,
                plan=lambda context: TransitionPlan(
                    "publish unsupported schema",
                    (
                        FileChange(
                            path,
                            "---\nschema: atelier.work/v2\n---\nUnsupported.\n",
                        ),
                    ),
                ),
            )
        self.assertEqual(self.remote_head(), before)

    def test_declared_non_mailbox_paths_fail_before_push(self) -> None:
        before = self.remote_head()
        for path in (
            "unexpected.txt",
            f"work/{self.work_id}/cache.json",
            f"projects/{fixtures.identifier('prj', 1)}/unexpected.md",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    MailboxTransitionRejected,
                    "unsafe mailbox path",
                ):
                    self.writer().publish(
                        "declare non-mailbox file",
                        revalidate=lambda context: None,
                        plan=lambda context, path=path: TransitionPlan(
                            "declare non-mailbox file",
                            (FileChange(path, "not mailbox state\n"),),
                        ),
                    )
                self.assertEqual(self.remote_head(), before)

    def test_callback_mutation_is_rejected_before_commit(self) -> None:
        before = self.remote_head()

        def plan(context: TransitionContext) -> TransitionPlan:
            (context.checkout / "unexpected.txt").write_text("hidden", encoding="utf-8")
            path, content = planner_message(self.work_id, 1)
            return TransitionPlan("hidden mutation", (FileChange(path, content),))

        with self.assertRaises(MailboxTransitionRejected):
            self.writer().publish(
                "hidden mutation",
                revalidate=lambda context: None,
                plan=plan,
            )
        self.assertEqual(self.remote_head(), before)

    def test_callback_history_mutation_cannot_publish_an_extra_commit(self) -> None:
        before = self.remote_head()

        def plan(context: TransitionContext) -> TransitionPlan:
            committed = run_git(
                context.checkout,
                (
                    "-c",
                    "user.name=Atelier Test",
                    "-c",
                    "user.email=atelier-test@invalid",
                    "commit",
                    "--quiet",
                    "--no-gpg-sign",
                    "--allow-empty",
                    "-m",
                    "hidden callback commit",
                ),
            )
            self.assertEqual(committed.returncode, 0)
            path, content = planner_message(self.work_id, 1)
            return TransitionPlan(
                "declared transition",
                (FileChange(path, content),),
            )

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "one commit directly atop the fetched base",
        ):
            self.writer().publish(
                "callback history mutation",
                revalidate=lambda context: None,
                plan=plan,
            )
        self.assertEqual(self.remote_head(), before)

    def test_commit_hook_content_mutation_fails_before_push(self) -> None:
        before = self.remote_head()
        path, content = planner_message(self.work_id, 1)

        def plan(context: TransitionContext) -> TransitionPlan:
            hook = context.checkout / ".git" / "hooks" / "pre-commit"
            hook.write_text(
                "#!/bin/sh\n"
                f"printf 'corrupted\\n' > {path}\n"
                f"git add -- {path}\n",
                encoding="utf-8",
            )
            hook.chmod(0o700)
            return TransitionPlan(
                "declared transition",
                (FileChange(path, content),),
            )

        with self.assertRaisesRegex(
            MailboxTransitionRejected,
            "committed mailbox content differs",
        ):
            self.writer().publish(
                "commit hook content mutation",
                revalidate=lambda context: None,
                plan=plan,
            )
        self.assertEqual(self.remote_head(), before)

    def test_existing_messages_and_receipts_are_append_only(self) -> None:
        remote = self.root / "append-only-mailbox.git"
        seed = self.root / "append-only-seed"
        git(None, "init", "--bare", "--initial-branch=main", str(remote))
        git(None, "clone", str(remote), str(seed))
        mailbox = fixtures.MailboxFixture(seed)
        work_id = mailbox.add_work(2, "blocked")
        git(seed, "add", "-A")
        git(
            seed,
            "-c",
            "user.name=Atelier Test",
            "-c",
            "user.email=atelier-test@invalid",
            "commit",
            "-m",
            "seed append-only artifacts",
        )
        git(seed, "push", "origin", "HEAD:main")
        before = git(seed, "rev-parse", "HEAD").stdout.strip()
        message_id = next(iter(mailbox.messages[work_id]))
        receipt_id = next(iter(mailbox.receipts[work_id]))
        paths = (
            f"work/{work_id}/messages/{message_id}.md",
            f"work/{work_id}/receipts/{receipt_id}.md",
        )
        writer = GitMailboxWriter(str(remote), "main")

        for path in paths:
            original = (seed / path).read_text(encoding="utf-8")
            for content in (original.replace("Fixture.", "Rewritten."), None):
                with self.subTest(path=path, deletion=content is None):
                    with self.assertRaisesRegex(
                        MailboxTransitionRejected,
                        "append-only mailbox document",
                    ):
                        writer.publish(
                            "mutate append-only artifact",
                            revalidate=lambda context: None,
                            plan=lambda context, path=path, content=content: TransitionPlan(
                                "mutate append-only artifact",
                                (FileChange(path, content),),
                            ),
                        )
                    head = git(
                        None,
                        "--git-dir",
                        str(remote),
                        "rev-parse",
                        "main",
                    ).stdout.strip()
                    self.assertEqual(head, before)

    def test_same_claim_checkpoint_ledger_cannot_be_rewritten_or_truncated(self) -> None:
        self._claim(with_candidate=True)
        before = self.remote_head()

        def mutate_checkpoint(
            context: TransitionContext,
            mutation: str,
        ) -> TransitionPlan:
            path = f"work/{self.work_id}/work.md"
            work = read_markdown(context.checkout / path)
            checkpoint = work["claim"]["checkpoint"]
            if mutation == "truncate":
                checkpoint["authorizations"] = checkpoint["authorizations"][:-1]
                checkpoint["sequence"] -= 1
            else:
                checkpoint["authorizations"][-1]["proposed_effect_digest"] = (
                    "sha256:" + ("f" * 64)
                )
            return TransitionPlan(
                f"{mutation} checkpoint ledger",
                (FileChange(path, markdown(work)),),
            )

        for mutation in ("truncate", "rewrite"):
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(
                    MailboxTransitionRejected,
                    "checkpoint authorization ledger is append-only",
                ):
                    self.writer().publish(
                        f"{mutation} checkpoint ledger",
                        revalidate=lambda context: None,
                        plan=lambda context, mutation=mutation: mutate_checkpoint(
                            context,
                            mutation,
                        ),
                    )
                self.assertEqual(self.remote_head(), before)

    def test_option_looking_remote_is_rejected_before_git_runs(self) -> None:
        calls: list[tuple[str, ...]] = []

        def recording_runner(
            cwd: Path | None,
            arguments: tuple[str, ...] | list[str],
        ) -> subprocess.CompletedProcess[str]:
            calls.append(tuple(arguments))
            return run_git(cwd, arguments)

        with self.assertRaisesRegex(ValueError, "must not begin"):
            GitMailboxWriter(
                "--upload-pack=/tmp/untrusted",
                "main",
                runner=recording_runner,
            )
        self.assertEqual(calls, [])

    def _append_instruction(self, number: int) -> None:
        path, content = planner_message(self.work_id, number)
        self.writer().publish(
            f"append instruction {number}",
            revalidate=lambda context: None,
            plan=lambda context: TransitionPlan(
                f"append instruction {number}",
                (FileChange(path, content),),
            ),
        )

    def _claim(self, *, with_candidate: bool = False) -> dict[str, Any]:
        claim_value = fixtures.claim(
            self.repository,
            1,
            with_candidate=with_candidate,
        )

        def plan(context: TransitionContext) -> TransitionPlan:
            work = read_markdown(context.checkout / f"work/{self.work_id}/work.md")
            work["status"] = "active"
            work["claim"] = copy.deepcopy(claim_value)
            return TransitionPlan(
                "claim work",
                (FileChange(f"work/{self.work_id}/work.md", markdown(work)),),
            )

        self.writer().publish(
            "claim work",
            revalidate=lambda context: None,
            plan=plan,
        )
        return claim_value
