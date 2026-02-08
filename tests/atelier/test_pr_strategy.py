from atelier import pr_strategy


def test_normalize_pr_strategy_defaults_to_sequential() -> None:
    assert pr_strategy.normalize_pr_strategy(None) == "sequential"
    assert pr_strategy.normalize_pr_strategy("") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_READY") == "on-ready"


def test_pr_strategy_decision_allows_parallel() -> None:
    decision = pr_strategy.pr_strategy_decision("parallel", parent_state="draft-pr")
    assert decision.allow_pr is True
    assert decision.strategy == "parallel"
    assert decision.reason == "strategy:parallel"


def test_pr_strategy_decision_sequential_blocks_on_open_parent() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="pr-open")
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pr-open"


def test_pr_strategy_decision_sequential_allows_when_parent_merged() -> None:
    decision = pr_strategy.pr_strategy_decision("sequential", parent_state="merged")
    assert decision.allow_pr is True
    assert decision.reason == "parent:merged"
