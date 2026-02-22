from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from atelier.worker.review import MergeConflictSelection, ReviewFeedbackSelection
from atelier.worker.session import startup


class FakeStartupService:
    def __init__(self, **overrides: Any) -> None:
        self._handle_queue_before_claim = overrides.pop(
            "handle_queue_before_claim", lambda *_args, **_kwargs: False
        )
        self._list_epics = overrides.pop("list_epics", lambda: [])
        self._next_changeset = overrides.pop("next_changeset", lambda **_kwargs: None)
        self._resolve_hooked_epic = overrides.pop("resolve_hooked_epic", lambda *_args: None)
        self._stale_family_assigned_epics = overrides.pop(
            "stale_family_assigned_epics", lambda issues, agent_id: []
        )
        self._select_conflicted_changeset = overrides.pop(
            "select_conflicted_changeset", lambda **_kwargs: None
        )
        self._select_global_conflicted_changeset = overrides.pop(
            "select_global_conflicted_changeset", lambda **_kwargs: None
        )
        self._select_review_feedback_changeset = overrides.pop(
            "select_review_feedback_changeset", lambda **_kwargs: None
        )
        self._select_global_review_feedback_changeset = overrides.pop(
            "select_global_review_feedback_changeset", lambda **_kwargs: None
        )
        self._check_inbox_before_claim = overrides.pop(
            "check_inbox_before_claim", lambda *_args: False
        )
        self._ready_changesets_global = overrides.pop("ready_changesets_global", lambda: [])
        self._select_epic_prompt = overrides.pop("select_epic_prompt", lambda **_kwargs: None)
        self._send_needs_decision = overrides.pop("send_needs_decision", lambda **_kwargs: None)
        self._dry_run_log = overrides.pop("dry_run_log", lambda _message: None)
        self._emit = overrides.pop("emit", lambda _message: None)
        self._die = overrides.pop(
            "die", lambda message: (_ for _ in ()).throw(RuntimeError(message))
        )
        if overrides:
            unexpected = ", ".join(sorted(overrides))
            raise ValueError(f"unexpected startup service overrides: {unexpected}")

    def handle_queue_before_claim(
        self,
        agent_id: str,
        *,
        queue_name: str,
        force_prompt: bool = False,
        dry_run: bool = False,
        assume_yes: bool = False,
    ) -> bool:
        return self._handle_queue_before_claim(
            agent_id,
            queue_name=queue_name,
            force_prompt=force_prompt,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )

    def list_epics(self) -> list[dict[str, object]]:
        return self._list_epics()

    def next_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> dict[str, object] | None:
        return self._next_changeset(
            epic_id=epic_id,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )

    def resolve_hooked_epic(self, agent_bead_id: str, agent_id: str) -> str | None:
        return self._resolve_hooked_epic(agent_bead_id, agent_id)

    def stale_family_assigned_epics(
        self, issues: list[dict[str, object]], *, agent_id: str
    ) -> list[dict[str, object]]:
        return self._stale_family_assigned_epics(issues, agent_id=agent_id)

    def select_conflicted_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
    ) -> MergeConflictSelection | None:
        return self._select_conflicted_changeset(
            epic_id=epic_id,
            repo_slug=repo_slug,
        )

    def select_global_conflicted_changeset(
        self,
        *,
        repo_slug: str | None,
    ) -> MergeConflictSelection | None:
        return self._select_global_conflicted_changeset(repo_slug=repo_slug)

    def select_review_feedback_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
    ) -> ReviewFeedbackSelection | None:
        return self._select_review_feedback_changeset(
            epic_id=epic_id,
            repo_slug=repo_slug,
        )

    def select_global_review_feedback_changeset(
        self,
        *,
        repo_slug: str | None,
    ) -> ReviewFeedbackSelection | None:
        return self._select_global_review_feedback_changeset(repo_slug=repo_slug)

    def check_inbox_before_claim(self, agent_id: str) -> bool:
        return self._check_inbox_before_claim(agent_id)

    def ready_changesets_global(self) -> list[dict[str, object]]:
        return self._ready_changesets_global()

    def select_epic_prompt(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
        is_actionable: Callable[[str], bool],
        assume_yes: bool,
    ) -> str | None:
        return self._select_epic_prompt(
            issues=issues,
            agent_id=agent_id,
            is_actionable=is_actionable,
            assume_yes=assume_yes,
        )

    def send_needs_decision(
        self,
        *,
        agent_id: str,
        mode: str,
        issues: list[dict[str, object]],
        dry_run: bool,
    ) -> None:
        self._send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            dry_run=dry_run,
        )

    def dry_run_log(self, message: str) -> None:
        self._dry_run_log(message)

    def emit(self, message: str) -> None:
        self._emit(message)

    def die(self, message: str) -> None:
        self._die(message)


def _startup_context_service(
    **overrides: Any,
) -> tuple[startup.StartupContractContext, FakeStartupService]:
    context_defaults: dict[str, Any] = {
        "agent_id": "atelier/worker/codex/p100",
        "agent_bead_id": "at-agent",
        "beads_root": Path("/beads"),
        "repo_root": Path("/repo"),
        "mode": "auto",
        "explicit_epic_id": None,
        "queue_only": False,
        "dry_run": False,
        "assume_yes": False,
        "repo_slug": None,
        "branch_pr": False,
        "branch_pr_strategy": "on-ready",
        "git_path": "git",
        "worker_queue_name": "worker",
    }
    context_values = dict(context_defaults)
    for key in list(context_defaults):
        if key in overrides:
            context_values[key] = overrides.pop(key)
    context = startup.StartupContractContext(**context_values)
    service = FakeStartupService(**overrides)
    return context, service


def _run_startup(**overrides: Any) -> startup.StartupContractResult:
    context, service = _startup_context_service(**overrides)
    return startup.run_startup_contract_service(context=context, service=service)


def test_run_startup_contract_service_supports_typed_context() -> None:
    context, service = _startup_context_service(explicit_epic_id="at-explicit")

    result = startup.run_startup_contract_service(context=context, service=service)

    assert result.epic_id == "at-explicit"
    assert result.should_exit is False
    assert result.reason == "explicit_epic"


def test_run_startup_contract_supports_explicit_epic() -> None:
    result = _run_startup(explicit_epic_id="at-explicit")

    assert result.epic_id == "at-explicit"
    assert result.should_exit is False
    assert result.reason == "explicit_epic"


def test_run_startup_contract_queue_only_exits_after_queue() -> None:
    queue_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def handle_queue(*args: Any, **kwargs: Any) -> bool:
        queue_calls.append((args, kwargs))
        return False

    result = _run_startup(queue_only=True, handle_queue_before_claim=handle_queue)

    assert result.should_exit is True
    assert result.reason == "queue_only"
    assert len(queue_calls) == 1
    assert queue_calls[0][1]["force_prompt"] is True


def test_run_startup_contract_prioritizes_review_feedback() -> None:
    feedback = ReviewFeedbackSelection(
        epic_id="at-epic",
        changeset_id="at-epic.1",
        feedback_at="2026-02-20T00:00:00Z",
    )
    next_changeset_calls = 0

    def next_changeset(**_kwargs: Any) -> dict[str, object] | None:
        nonlocal next_changeset_calls
        next_changeset_calls += 1
        return {"id": "at-epic.2"}

    result = _run_startup(
        branch_pr=True,
        repo_slug="org/repo",
        resolve_hooked_epic=lambda *_args: "at-epic",
        select_review_feedback_changeset=lambda **_kwargs: feedback,
        next_changeset=next_changeset,
        list_epics=lambda: [{"id": "at-epic", "assignee": "atelier/worker/codex/p100"}],
    )

    assert result.reason == "review_feedback"
    assert result.epic_id == "at-epic"
    assert result.changeset_id == "at-epic.1"
    assert next_changeset_calls == 0


def test_run_startup_contract_prioritizes_merge_conflict() -> None:
    conflict = MergeConflictSelection(
        epic_id="at-epic",
        changeset_id="at-epic.3",
        observed_at="2026-02-20T00:00:00Z",
        pr_url="https://github.com/org/repo/pull/103",
    )
    next_changeset_calls = 0

    def next_changeset(**_kwargs: Any) -> dict[str, object] | None:
        nonlocal next_changeset_calls
        next_changeset_calls += 1
        return {"id": "at-epic.2"}

    result = _run_startup(
        branch_pr=True,
        repo_slug="org/repo",
        resolve_hooked_epic=lambda *_args: "at-epic",
        select_conflicted_changeset=lambda **_kwargs: conflict,
        next_changeset=next_changeset,
        list_epics=lambda: [{"id": "at-epic", "assignee": "atelier/worker/codex/p010"}],
    )

    assert result.reason == "merge_conflict"
    assert result.epic_id == "at-epic"
    assert result.changeset_id == "at-epic.3"
    assert next_changeset_calls == 0


def test_run_startup_contract_skips_non_claimable_review_feedback_epic() -> None:
    seen_epics: list[str] = []
    claimable_feedback = ReviewFeedbackSelection(
        epic_id="at-claimable",
        changeset_id="at-claimable.1",
        feedback_at="2026-02-20T00:00:00Z",
    )
    blocked_feedback = ReviewFeedbackSelection(
        epic_id="at-blocked",
        changeset_id="at-blocked.1",
        feedback_at="2026-02-19T00:00:00Z",
    )

    def select_feedback(*, epic_id: str, repo_slug: str | None) -> ReviewFeedbackSelection | None:
        _ = repo_slug
        seen_epics.append(epic_id)
        if epic_id == "at-claimable":
            return claimable_feedback
        if epic_id == "at-blocked":
            return blocked_feedback
        return None

    result = _run_startup(
        branch_pr=True,
        repo_slug="org/repo",
        list_epics=lambda: [
            {
                "id": "at-blocked",
                "status": "open",
                "assignee": "atelier/planner/codex/p001",
                "created_at": "2026-02-20T00:00:00Z",
            },
            {
                "id": "at-claimable",
                "status": "open",
                "assignee": None,
                "created_at": "2026-02-21T00:00:00Z",
            },
        ],
        next_changeset=lambda **_kwargs: {"id": "at-next.1"},
        select_review_feedback_changeset=select_feedback,
        select_global_review_feedback_changeset=lambda **_kwargs: None,
    )

    assert result.reason == "review_feedback"
    assert result.epic_id == "at-claimable"
    assert result.changeset_id == "at-claimable.1"
    assert seen_epics == ["at-claimable"]


def test_run_startup_contract_selects_stale_reclaimable_review_feedback() -> None:
    stale_issue = {
        "id": "at-stale",
        "status": "open",
        "assignee": "atelier/worker/codex/p099",
        "created_at": "2026-02-20T00:00:00Z",
    }
    feedback = ReviewFeedbackSelection(
        epic_id="at-stale",
        changeset_id="at-stale.1",
        feedback_at="2026-02-20T00:00:00Z",
    )

    result = _run_startup(
        branch_pr=True,
        repo_slug="org/repo",
        list_epics=lambda: [stale_issue],
        stale_family_assigned_epics=lambda _issues, agent_id: [stale_issue],
        next_changeset=lambda **_kwargs: {"id": "at-stale.2"},
        select_review_feedback_changeset=lambda **_kwargs: feedback,
    )

    assert result.reason == "review_feedback"
    assert result.epic_id == "at-stale"
    assert result.changeset_id == "at-stale.1"
    assert result.reassign_from == "atelier/worker/codex/p099"


def test_run_startup_contract_skips_unclaimable_global_review_feedback() -> None:
    blocked_feedback = ReviewFeedbackSelection(
        epic_id="at-blocked",
        changeset_id="at-blocked.1",
        feedback_at="2026-02-19T00:00:00Z",
    )

    result = _run_startup(
        branch_pr=True,
        repo_slug="org/repo",
        list_epics=lambda: [
            {
                "id": "at-blocked",
                "status": "open",
                "assignee": "atelier/planner/codex/p001",
                "created_at": "2026-02-20T00:00:00Z",
            },
            {
                "id": "at-claimable",
                "status": "open",
                "assignee": None,
                "created_at": "2026-02-21T00:00:00Z",
            },
        ],
        next_changeset=lambda **kwargs: {"id": f"{kwargs['epic_id']}.1"},
        select_review_feedback_changeset=lambda **_kwargs: None,
        select_global_review_feedback_changeset=lambda **_kwargs: blocked_feedback,
    )

    assert result.reason == "selected_auto"
    assert result.epic_id == "at-claimable"


def test_run_startup_contract_reclaims_stale_family_assignment() -> None:
    issues = [{"id": "at-epic", "assignee": "atelier/worker/codex/p099"}]

    result = _run_startup(
        agent_bead_id=None,
        list_epics=lambda: issues,
        stale_family_assigned_epics=lambda _issues, agent_id: issues,
        next_changeset=lambda **_kwargs: {"id": "at-epic.1"},
    )

    assert result.reason == "stale_assignee_epic"
    assert result.epic_id == "at-epic"
    assert result.reassign_from == "atelier/worker/codex/p099"


def test_run_startup_contract_uses_ready_changeset_fallback() -> None:
    issues = [{"id": "at-other"}]

    result = _run_startup(
        list_epics=lambda: issues,
        mode="prompt",
        select_epic_prompt=lambda **_kwargs: None,
        ready_changesets_global=lambda: [{"id": "at-ready"}],
        next_changeset=lambda **_kwargs: {"id": "at-ready"},
    )

    assert result.reason == "selected_ready_changeset"
    assert result.epic_id == "at-ready"


def test_run_startup_contract_selects_auto_epic() -> None:
    issues = [{"id": "at-auto", "status": "open"}]

    result = _run_startup(
        list_epics=lambda: issues,
        next_changeset=lambda **_kwargs: {"id": "at-auto.1"},
    )

    assert result.reason == "selected_auto"
    assert result.epic_id == "at-auto"


def test_run_startup_contract_sends_needs_decision_when_no_eligible_epics() -> None:
    sent: list[dict[str, Any]] = []

    result = _run_startup(
        send_needs_decision=lambda **kwargs: sent.append(kwargs),
        list_epics=lambda: [],
    )

    assert result.should_exit is True
    assert result.reason == "no_eligible_epics"
    assert len(sent) == 1
