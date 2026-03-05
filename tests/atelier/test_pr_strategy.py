import pytest

from atelier import pr_strategy


def test_normalize_pr_strategy_defaults_to_sequential() -> None:
    assert pr_strategy.normalize_pr_strategy(None) == "sequential"
    assert pr_strategy.normalize_pr_strategy("") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_READY") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_PARENT_APPROVED") == "sequential"
    assert pr_strategy.normalize_pr_strategy("parallel") == "sequential"


def test_pr_strategy_decision_sequential_blocks_on_open_parent() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="pr-open")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pr-open"


def test_pr_strategy_decision_legacy_values_still_apply_sequential_policy() -> None:
    decision = pr_strategy.pr_strategy_decision("on-ready", parent_state="pushed")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pushed"

    parallel = pr_strategy.pr_strategy_decision("parallel", parent_state="approved")
    assert parallel.allow_pr is False
    assert parallel.reason == "blocked:approved"


def test_pr_strategy_decision_allows_when_parent_is_integrated() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="merged")
    assert decision.allow_pr is True
    assert decision.reason == "parent:merged"

    closed = pr_strategy.pr_strategy_decision("sequential", parent_state="closed")
    assert closed.allow_pr is False
    assert closed.reason == "blocked:closed"


@pytest.mark.parametrize(
    ("parent_state", "allow_pr", "reason"),
    [
        ("draft-pr", False, "blocked:draft-pr"),
        ("pr-open", False, "blocked:pr-open"),
        ("in-review", False, "blocked:in-review"),
        ("approved", False, "blocked:approved"),
        ("merged", True, "parent:merged"),
        ("closed", False, "blocked:closed"),
    ],
)
def test_pr_strategy_decision_applies_sequential_policy(
    parent_state: str,
    allow_pr: bool,
    reason: str,
) -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state=parent_state)
    assert decision.allow_pr is allow_pr
    assert decision.reason == reason


def test_normalize_pr_strategy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="pr_strategy must be one of: sequential"):
        pr_strategy.normalize_pr_strategy("custom")
