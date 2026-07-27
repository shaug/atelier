#!/usr/bin/env python3
"""Persist one verified semantic transition to an Atelier Git mailbox."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .mailbox import _parse_yaml, _read_yaml, reconstruct_mailbox

READBACK_REF = "refs/remotes/atelier/canonical"
GIT_COMMAND_TIMEOUT_SECONDS = 30


class MailboxWriteError(RuntimeError):
    """A mailbox write cannot safely report success."""


class MailboxRemoteUnavailable(MailboxWriteError):
    """The canonical mailbox branch could not be fetched before mutation."""


class MailboxTransitionRejected(MailboxWriteError):
    """Fresh semantic preconditions reject the proposed transition."""


class MailboxReadBackError(MailboxWriteError):
    """Remote history does not contain the exact content attributed to a commit."""


class MailboxRetryExhausted(MailboxWriteError):
    """Contention persisted beyond the bounded retry budget."""


@dataclass(frozen=True)
class FileChange:
    """One complete UTF-8 document replacement or deletion."""

    path: str
    content: str | None


@dataclass(frozen=True)
class TransitionPlan:
    """The complete durable effect of one semantic transition."""

    commit_message: str
    changes: tuple[FileChange, ...]


@dataclass(frozen=True)
class TransitionContext:
    """Fresh mailbox state supplied to precondition and planning callbacks."""

    checkout: Path
    base_revision: str
    snapshot: Mapping[str, Any]
    attempt: int


@dataclass(frozen=True)
class PendingWrite:
    """A pushed commit whose remote outcome could not yet be verified."""

    operation: str
    branch: str
    commit: str
    base_revision: str
    changes: tuple[FileChange, ...]


class MailboxPersistenceUnknown(MailboxWriteError):
    """A push may have succeeded, but exact remote read-back was unavailable."""

    def __init__(self, pending: PendingWrite):
        self.pending = pending
        super().__init__(
            f"{pending.operation}: persistence outcome is unknown for commit {pending.commit}"
        )


@dataclass(frozen=True)
class WriteResult:
    """Verified remote identity for one published transition."""

    operation: str
    branch: str
    commit: str
    base_revision: str
    attempts: int
    recovered: bool


class GitRunner(Protocol):
    """Injectable Git command boundary used by production code and fault tests."""

    def __call__(
        self,
        cwd: Path | None,
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]: ...


Revalidate = Callable[[TransitionContext], None]
PlanTransition = Callable[[TransitionContext], TransitionPlan]


def _valid_mailbox_document_path(path: PurePosixPath) -> bool:
    parts = path.parts
    if parts == ("atelier.yaml",):
        return True
    if len(parts) == 3:
        collection, identifier, document = parts
        return (
            collection == "projects"
            and identifier.startswith("prj_")
            and document == "project.md"
        ) or (
            collection == "initiatives"
            and identifier.startswith("ini_")
            and document == "initiative.md"
        ) or (
            collection == "work"
            and identifier.startswith("wrk_")
            and document == "work.md"
        )
    if len(parts) == 4 and parts[0] == "work" and parts[1].startswith("wrk_"):
        collection, document = parts[2:]
        return (
            collection == "messages"
            and document.startswith("msg_")
            and document.endswith(".md")
        ) or (
            collection == "receipts"
            and document.startswith("rcp_")
            and document.endswith(".md")
        )
    return False


def run_git(
    cwd: Path | None,
    arguments: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    """Run Git without inheriting repository-scoped environment variables."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_PREFIX",
        }
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_COMMAND_TIMEOUT_SECONDS,
    )


class GitMailboxWriter:
    """Fast-forward, compare-and-swap writer for one canonical mailbox branch."""

    def __init__(
        self,
        remote: str,
        branch: str,
        *,
        max_attempts: int = 3,
        runner: GitRunner = run_git,
    ):
        if not remote:
            raise ValueError("remote must not be empty")
        if remote.startswith("-"):
            raise ValueError("remote must not begin with '-'")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.remote = remote
        self.branch = branch
        self.max_attempts = max_attempts
        self._run = runner
        branch_check = self._run(None, ("check-ref-format", "--branch", branch))
        if branch_check.returncode != 0:
            raise ValueError(f"invalid canonical branch: {branch}")

    def publish(
        self,
        operation: str,
        *,
        revalidate: Revalidate,
        plan: PlanTransition,
    ) -> WriteResult:
        """Publish one transition, replanning only after fresh revalidation."""

        if not operation.strip():
            raise ValueError("operation must not be empty")
        with tempfile.TemporaryDirectory(prefix="atelier-mailbox-write-") as temporary:
            checkout = Path(temporary) / "mailbox"
            self._initialize(checkout)
            for attempt in range(1, self.max_attempts + 1):
                base_revision = self._fetch_current(checkout)
                self._reset(checkout)
                snapshot = reconstruct_mailbox(checkout)
                if snapshot["canonical_branch"] != self.branch:
                    raise MailboxTransitionRejected(
                        f"{operation}: manifest canonical branch "
                        f"{snapshot['canonical_branch']!r} does not match {self.branch!r}"
                    )
                context = TransitionContext(
                    checkout=checkout,
                    base_revision=base_revision,
                    snapshot=snapshot,
                    attempt=attempt,
                )
                revalidate(context)
                transition = plan(context)
                changes = self._normalize_plan(checkout, transition)
                prior_claims = self._read_prior_claims(checkout, changes)
                self._apply(checkout, changes)
                reconstruct_mailbox(checkout)
                self._verify_claim_history(checkout, prior_claims, changes)
                self._stage_exact_changes(checkout, changes)
                commit = self._commit(checkout, transition.commit_message)
                self._verify_commit_shape(
                    checkout,
                    commit=commit,
                    base_revision=base_revision,
                    changes=changes,
                )
                pending = PendingWrite(
                    operation=operation,
                    branch=self.branch,
                    commit=commit,
                    base_revision=base_revision,
                    changes=changes,
                )
                try:
                    pushed = self._run(
                        checkout,
                        (
                            "push",
                            "--porcelain",
                            f"--force-with-lease=refs/heads/{self.branch}:{base_revision}",
                            self.remote,
                            f"{commit}:refs/heads/{self.branch}",
                        ),
                    )
                except subprocess.TimeoutExpired:
                    pushed = None
                try:
                    recovered = pushed is None or pushed.returncode != 0
                    if self._read_back(checkout, pending):
                        return WriteResult(
                            operation=operation,
                            branch=self.branch,
                            commit=commit,
                            base_revision=base_revision,
                            attempts=attempt,
                            recovered=recovered,
                        )
                except MailboxRemoteUnavailable as error:
                    raise MailboxPersistenceUnknown(pending) from error
                if pushed is not None and pushed.returncode == 0:
                    raise MailboxReadBackError(
                        f"{operation}: successful push omitted commit {commit} from remote history"
                    )
                self._require_canonical_descendant(
                    checkout,
                    base_revision=base_revision,
                    operation=operation,
                )
                if attempt == self.max_attempts:
                    raise MailboxRetryExhausted(
                        f"{operation}: remote contention exceeded {self.max_attempts} attempts"
                    )
            raise AssertionError("bounded mailbox write loop terminated unexpectedly")

    def recover(self, pending: PendingWrite) -> WriteResult | None:
        """Resolve an ambiguous push through ancestry and exact historical content."""

        if pending.branch != self.branch:
            raise ValueError("pending write belongs to a different canonical branch")
        with tempfile.TemporaryDirectory(prefix="atelier-mailbox-recover-") as temporary:
            checkout = Path(temporary) / "mailbox"
            self._initialize(checkout)
            if not self._read_back(checkout, pending):
                self._require_canonical_descendant(
                    checkout,
                    base_revision=pending.base_revision,
                    operation=pending.operation,
                )
                return None
        return WriteResult(
            operation=pending.operation,
            branch=pending.branch,
            commit=pending.commit,
            base_revision=pending.base_revision,
            attempts=0,
            recovered=True,
        )

    def _initialize(self, checkout: Path) -> None:
        checkout.mkdir(parents=True)
        initialized = self._run(checkout, ("init", "--quiet"))
        if initialized.returncode != 0:
            raise MailboxWriteError("could not initialize isolated mailbox checkout")

    def _fetch_current(self, checkout: Path) -> str:
        try:
            fetched = self._run(
                checkout,
                (
                    "fetch",
                    "--no-tags",
                    self.remote,
                    f"+refs/heads/{self.branch}:{READBACK_REF}",
                ),
            )
        except subprocess.TimeoutExpired as error:
            raise MailboxRemoteUnavailable(
                f"canonical mailbox branch {self.branch!r} timed out"
            ) from error
        if fetched.returncode != 0:
            raise MailboxRemoteUnavailable(
                f"canonical mailbox branch {self.branch!r} is unavailable"
            )
        return self._output(checkout, ("rev-parse", READBACK_REF), "resolve canonical mailbox head")

    def _reset(self, checkout: Path) -> None:
        reset = self._run(checkout, ("reset", "--hard", "--quiet", READBACK_REF))
        cleaned = self._run(checkout, ("clean", "-ffdqx"))
        if reset.returncode != 0 or cleaned.returncode != 0:
            raise MailboxWriteError("could not reset isolated checkout to the fetched mailbox")

    def _normalize_plan(
        self,
        checkout: Path,
        transition: TransitionPlan,
    ) -> tuple[FileChange, ...]:
        if not transition.commit_message.strip():
            raise MailboxTransitionRejected("transition commit message must not be empty")
        dirty = self._run(checkout, ("status", "--porcelain", "--untracked-files=all"))
        if dirty.returncode != 0 or dirty.stdout:
            raise MailboxTransitionRejected("transition callback mutated its read-only context")
        if not transition.changes:
            raise MailboxTransitionRejected("transition must change at least one document")
        by_path: dict[str, FileChange] = {}
        for change in transition.changes:
            pure = PurePosixPath(change.path)
            if (
                pure.is_absolute()
                or not change.path
                or change.path != pure.as_posix()
                or ".." in pure.parts
                or ".git" in pure.parts
                or not _valid_mailbox_document_path(pure)
            ):
                raise MailboxTransitionRejected(f"unsafe mailbox path: {change.path!r}")
            if change.path in by_path:
                raise MailboxTransitionRejected(f"duplicate mailbox path: {change.path}")
            append_only = (
                len(pure.parts) == 4
                and pure.parts[0] == "work"
                and pure.parts[2] in {"messages", "receipts"}
            )
            if append_only and change.content is None:
                raise MailboxTransitionRejected(
                    f"{change.path}: append-only mailbox documents cannot be deleted"
                )
            if append_only and (checkout / change.path).exists():
                raise MailboxTransitionRejected(
                    f"{change.path}: append-only mailbox document already exists"
                )
            if change.content is not None:
                try:
                    change.content.encode("utf-8")
                except UnicodeEncodeError as error:
                    raise MailboxTransitionRejected(
                        f"{change.path}: mailbox documents must be UTF-8"
                    ) from error
            by_path[change.path] = change
        return tuple(by_path[path] for path in sorted(by_path))

    def _read_prior_claims(
        self,
        checkout: Path,
        changes: tuple[FileChange, ...],
    ) -> dict[str, Mapping[str, Any] | None]:
        prior_claims: dict[str, Mapping[str, Any] | None] = {}
        for change in changes:
            pure = PurePosixPath(change.path)
            if (
                len(pure.parts) != 3
                or pure.parts[0] != "work"
                or pure.parts[2] != "work.md"
                or change.content is None
            ):
                continue
            target = checkout / change.path
            if target.exists():
                document, _ = _read_yaml(target, frontmatter=True, label=change.path)
                prior_claims[change.path] = document["claim"]
            else:
                prior_claims[change.path] = None
        return prior_claims

    def _verify_claim_history(
        self,
        checkout: Path,
        prior_claims: Mapping[str, Mapping[str, Any] | None],
        changes: tuple[FileChange, ...],
    ) -> None:
        for path, prior_claim in prior_claims.items():
            document, _ = _read_yaml(checkout / path, frontmatter=True, label=path)
            current_claim = document["claim"]
            if current_claim is None:
                continue
            if prior_claim is None:
                self._verify_new_claim(checkout, path, current_claim)
                continue
            if current_claim["id"] != prior_claim["id"]:
                if current_claim["candidate"] != prior_claim["candidate"]:
                    raise MailboxTransitionRejected(
                        f"{path}: takeover must preserve the prior claim candidate"
                    )
                self._verify_new_claim(checkout, path, current_claim)
                work_id = PurePosixPath(path).parts[1]
                for change in changes:
                    receipt_path = PurePosixPath(change.path)
                    if (
                        change.content is None
                        or len(receipt_path.parts) != 4
                        or receipt_path.parts[:3] != ("work", work_id, "receipts")
                    ):
                        continue
                    receipt, _ = _read_yaml(
                        checkout / change.path,
                        frontmatter=True,
                        label=change.path,
                    )
                    if (
                        receipt["outcome"] == "released"
                        and receipt["claim_id"] == prior_claim["id"]
                    ):
                        raise MailboxTransitionRejected(
                            f"{path}: release and new claim require distinct transitions"
                        )
                continue
            binding_fields = (
                "worker_run_id",
                "work_revision",
                "approved_commit",
                "policy_commit",
                "ticket_observation_digest",
                "claimed_at",
                "host",
            )
            if any(current_claim[field] != prior_claim[field] for field in binding_fields):
                raise MailboxTransitionRejected(
                    f"{path}: current claim authority bindings are immutable"
                )
            prior_checkpoint = prior_claim["checkpoint"]
            current_checkpoint = current_claim["checkpoint"]
            prior_ledger = prior_checkpoint["authorizations"]
            current_ledger = current_checkpoint["authorizations"]
            sequence_delta = current_checkpoint["sequence"] - prior_checkpoint["sequence"]
            if current_ledger[: len(prior_ledger)] != prior_ledger:
                raise MailboxTransitionRejected(
                    f"{path}: checkpoint authorization ledger is append-only"
                )
            if sequence_delta not in {0, 1}:
                raise MailboxTransitionRejected(
                    f"{path}: one transition may advance only one checkpoint sequence"
                )
            expected_ledger_size = len(prior_ledger) + sequence_delta
            if len(current_ledger) != expected_ledger_size:
                raise MailboxTransitionRejected(
                    f"{path}: one checkpoint sequence requires one authorization entry"
                )
            token_rotated = (
                current_checkpoint["continuation_token"]
                != prior_checkpoint["continuation_token"]
            )
            if (sequence_delta == 1) != token_rotated:
                raise MailboxTransitionRejected(
                    f"{path}: checkpoint sequence and continuation token must advance together"
                )
            if current_claim["candidate"] != prior_claim["candidate"]:
                if sequence_delta != 1 or current_claim["candidate"] is None:
                    raise MailboxTransitionRejected(
                        f"{path}: candidate changes require one publication checkpoint"
                    )
                publication = current_ledger[-1]
                candidate_head = current_claim["candidate"]["head_revision"]
                if (
                    publication["phase"] != "candidate_published"
                    or publication["candidate_head"] != candidate_head
                    or publication["acknowledged_candidate_head"] != candidate_head
                ):
                    raise MailboxTransitionRejected(
                        f"{path}: candidate publication checkpoint does not match candidate"
                    )

    def _verify_new_claim(
        self,
        checkout: Path,
        path: str,
        claim: Mapping[str, Any],
    ) -> None:
        checkpoint = claim["checkpoint"]
        if checkpoint["sequence"] != 0 or checkpoint["authorizations"]:
            raise MailboxTransitionRejected(
                f"{path}: a new claim must begin with an empty checkpoint ledger"
            )
        historical_claims, historical_runs = self._historical_claim_identities(checkout)
        if claim["id"] in historical_claims or claim["worker_run_id"] in historical_runs:
            raise MailboxTransitionRejected(
                f"{path}: released or replaced claim identities cannot become current again"
            )

    def _historical_claim_identities(
        self,
        checkout: Path,
    ) -> tuple[set[str], set[str]]:
        work_pathspec = ":(glob)work/*/work.md"
        revisions = self._output_lines(
            checkout,
            ("log", "--format=%H", READBACK_REF, "--", work_pathspec),
            "inspect historical claim identities",
        )
        claim_ids: set[str] = set()
        worker_run_ids: set[str] = set()
        for revision in revisions:
            changed_paths = self._output_lines(
                checkout,
                (
                    "diff-tree",
                    "--root",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    revision,
                    "--",
                    work_pathspec,
                ),
                "inspect historical work document paths",
            )
            for path in changed_paths:
                shown = self._run(checkout, ("show", f"{revision}:{path}"))
                if shown.returncode != 0:
                    continue
                lines = shown.stdout.splitlines()
                if not lines or lines[0] != "---":
                    raise MailboxTransitionRejected(
                        f"{path}: historical work document has invalid frontmatter"
                    )
                try:
                    end = lines.index("---", 1)
                except ValueError as error:
                    raise MailboxTransitionRejected(
                        f"{path}: historical work document has invalid frontmatter"
                    ) from error
                document = _parse_yaml(
                    "\n".join(lines[1:end]),
                    f"{path}@{revision}",
                )
                historical_claim = document["claim"]
                if historical_claim is not None:
                    claim_ids.add(historical_claim["id"])
                    worker_run_ids.add(historical_claim["worker_run_id"])
        return claim_ids, worker_run_ids

    def _apply(self, checkout: Path, changes: tuple[FileChange, ...]) -> None:
        for change in changes:
            target = checkout / change.path
            if change.content is None:
                if target.exists():
                    if not target.is_file() or target.is_symlink():
                        raise MailboxTransitionRejected(
                            f"{change.path}: only ordinary document files may be deleted"
                        )
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and (not target.is_file() or target.is_symlink()):
                raise MailboxTransitionRejected(
                    f"{change.path}: only ordinary document files may be replaced"
                )
            target.write_text(change.content, encoding="utf-8")

    def _stage_exact_changes(
        self,
        checkout: Path,
        changes: tuple[FileChange, ...],
    ) -> None:
        staged = self._run(checkout, ("add", "-A"))
        if staged.returncode != 0:
            raise MailboxWriteError("could not stage mailbox transition")
        changed = self._output_lines(
            checkout,
            ("diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB"),
            "inspect staged mailbox transition",
        )
        declared = sorted(change.path for change in changes)
        if changed != declared:
            raise MailboxTransitionRejected(
                "staged mailbox transition differs from its declared document set"
            )

    def _commit(self, checkout: Path, message: str) -> str:
        committed = self._run(
            checkout,
            (
                "-c",
                "user.name=Atelier",
                "-c",
                "user.email=atelier@invalid",
                "commit",
                "--quiet",
                "--no-gpg-sign",
                "-m",
                message,
            ),
        )
        if committed.returncode != 0:
            raise MailboxWriteError("could not commit mailbox transition")
        return self._output(checkout, ("rev-parse", "HEAD"), "resolve mailbox commit")

    def _verify_commit_shape(
        self,
        checkout: Path,
        *,
        commit: str,
        base_revision: str,
        changes: tuple[FileChange, ...],
    ) -> None:
        lineage = self._output(
            checkout,
            ("rev-list", "--parents", "-n", "1", commit),
            "inspect mailbox commit lineage",
        ).split()
        if lineage != [commit, base_revision]:
            raise MailboxTransitionRejected(
                "mailbox transition must be one commit directly atop the fetched base"
            )
        changed = self._output_lines(
            checkout,
            ("diff-tree", "--no-commit-id", "--name-only", "-r", commit),
            "inspect committed mailbox transition",
        )
        declared = sorted(change.path for change in changes)
        if changed != declared:
            raise MailboxTransitionRejected(
                "committed mailbox transition differs from its declared document set"
            )
        for change in changes:
            shown = self._run(checkout, ("show", f"{commit}:{change.path}"))
            if change.content is None:
                if shown.returncode == 0:
                    raise MailboxTransitionRejected(
                        f"committed mailbox transition retained deleted path {change.path}"
                    )
            elif shown.returncode != 0 or shown.stdout != change.content:
                raise MailboxTransitionRejected(
                    f"committed mailbox content differs from declaration for {change.path}"
                )

    def _read_back(self, checkout: Path, pending: PendingWrite) -> bool:
        self._fetch_current(checkout)
        exists = self._run(checkout, ("cat-file", "-e", f"{pending.commit}^{{commit}}"))
        if exists.returncode != 0:
            return False
        ancestry = self._run(
            checkout,
            ("merge-base", "--is-ancestor", pending.commit, READBACK_REF),
        )
        if ancestry.returncode == 1:
            return False
        if ancestry.returncode != 0:
            raise MailboxReadBackError(
                f"{pending.operation}: could not verify commit ancestry"
            )
        for change in pending.changes:
            shown = self._run(checkout, ("show", f"{pending.commit}:{change.path}"))
            if change.content is None:
                if shown.returncode == 0:
                    raise MailboxReadBackError(
                        f"{pending.operation}: {change.path} exists in the verified commit"
                    )
            elif shown.returncode != 0 or shown.stdout != change.content:
                raise MailboxReadBackError(
                    f"{pending.operation}: {change.path} differs in the verified commit"
                )
        return True

    def _require_canonical_descendant(
        self,
        checkout: Path,
        *,
        base_revision: str,
        operation: str,
    ) -> None:
        ancestry = self._run(
            checkout,
            ("merge-base", "--is-ancestor", base_revision, READBACK_REF),
        )
        if ancestry.returncode == 1:
            raise MailboxTransitionRejected(
                f"{operation}: canonical mailbox branch moved backwards or diverged"
            )
        if ancestry.returncode != 0:
            raise MailboxReadBackError(
                f"{operation}: could not verify canonical branch continuity"
            )

    def _output(self, cwd: Path, arguments: Sequence[str], purpose: str) -> str:
        result = self._run(cwd, arguments)
        if result.returncode != 0:
            raise MailboxWriteError(f"could not {purpose}")
        return result.stdout.strip()

    def _output_lines(self, cwd: Path, arguments: Sequence[str], purpose: str) -> list[str]:
        output = self._output(cwd, arguments, purpose)
        return sorted(line for line in output.splitlines() if line)


def require_git() -> None:
    """Raise an exact bootstrap error when Git is unavailable."""

    if shutil.which("git") is None:
        raise MailboxWriteError("Git is required for canonical mailbox writes")
