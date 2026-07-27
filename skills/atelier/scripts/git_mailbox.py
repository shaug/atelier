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

from .mailbox import reconstruct_mailbox

READBACK_REF = "refs/remotes/atelier/canonical"


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
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
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
                self._apply(checkout, changes)
                reconstruct_mailbox(checkout)
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
                pushed = self._run(
                    checkout,
                    ("push", "--porcelain", self.remote, f"{commit}:refs/heads/{self.branch}"),
                )
                try:
                    recovered = pushed.returncode != 0
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
                if pushed.returncode == 0:
                    raise MailboxReadBackError(
                        f"{operation}: successful push omitted commit {commit} from remote history"
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
        fetched = self._run(
            checkout,
            (
                "fetch",
                "--no-tags",
                self.remote,
                f"+refs/heads/{self.branch}:{READBACK_REF}",
            ),
        )
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
            if change.content is not None:
                try:
                    change.content.encode("utf-8")
                except UnicodeEncodeError as error:
                    raise MailboxTransitionRejected(
                        f"{change.path}: mailbox documents must be UTF-8"
                    ) from error
            by_path[change.path] = change
        return tuple(by_path[path] for path in sorted(by_path))

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
