import pytest

from atelier import pr_strategy


def test_normalize_pr_strategy_defaults_to_sequential() -> None:
    assert pr_strategy.normalize_pr_strategy(None) == "sequential"
    assert pr_strategy.normalize_pr_strategy("") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_READY") == "on-ready"
    assert pr_strategy.normalize_pr_strategy("ON_PARENT_APPROVED") == "on-parent-approved"


def test_pr_strategy_decision_allows_parallel() -> None:
    decision = pr_strategy.pr_strategy_decision("parallel", parent_state="draft-pr")
    assert decision.allow_pr is True
    assert decision.strategy == "parallel"
    assert decision.reason == "strategy:parallel"


def test_pr_strategy_decision_sequential_blocks_on_open_parent() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="pr-open")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pr-open"


def test_pr_strategy_decision_on_ready_blocks_until_parent_pr_exists() -> None:
    decision = pr_strategy.pr_strategy_decision("on-ready", parent_state="pushed")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pushed"


def test_pr_strategy_decision_on_ready_allows_with_parent_pr_state() -> None:
    decision = pr_strategy.pr_strategy_decision("on-ready", parent_state="draft-pr")
    assert decision.allow_pr is True
    assert decision.reason == "parent:draft-pr"


def test_pr_strategy_decision_on_parent_approved_blocks_until_parent_approved() -> None:
    blocked = pr_strategy.pr_strategy_decision("on-parent-approved", parent_state="in-review")
    assert blocked.allow_pr is False
    assert blocked.reason == "blocked:in-review"

    allowed = pr_strategy.pr_strategy_decision("on-parent-approved", parent_state="approved")
    assert allowed.allow_pr is True
    assert allowed.reason == "parent:approved"


def test_pr_strategy_decision_sequential_allows_when_parent_merged() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="merged")
    assert decision.allow_pr is True
    assert decision.reason == "parent:merged"


@pytest.mark.parametrize(
    ("strategy", "parent_state", "allow_pr", "reason"),
    [
        ("parallel", "closed", True, "strategy:parallel"),
        ("parallel", "pr-open", True, "strategy:parallel"),
        ("on-ready", "pushed", False, "blocked:pushed"),
        ("on-ready", "pr-open", True, "parent:pr-open"),
    ],
)
def test_pr_strategy_decision_preserves_parallel_and_on_ready_behavior(
    strategy: str,
    parent_state: str,
    allow_pr: bool,
    reason: str,
) -> None:
    decision = pr_strategy.pr_strategy_decision(strategy, parent_state=parent_state)
    assert decision.allow_pr is allow_pr
    assert decision.reason == reason


def test_pr_strategy_decision_sequential_blocks_when_parent_closed() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="closed")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:closed"


def test_pr_strategy_decision_on_parent_approved_allows_closed_parent() -> None:
    decision = pr_strategy.pr_strategy_decision("on-parent-approved", parent_state="closed")
    assert decision.allow_pr is True
    assert decision.reason == "parent:closed"
