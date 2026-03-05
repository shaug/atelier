import pytest

from atelier import pr_strategy


def test_normalize_pr_strategy_defaults_to_sequential() -> None:
    assert pr_strategy.normalize_pr_strategy(None) == "sequential"
    assert pr_strategy.normalize_pr_strategy("") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_READY") == "sequential"
    assert pr_strategy.normalize_pr_strategy("ON_PARENT_APPROVED") == "sequential"
    assert pr_strategy.normalize_pr_strategy("parallel") == "sequential"


def test_normalize_pr_strategy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="pr_strategy must be one of: sequential"):
        pr_strategy.normalize_pr_strategy("custom")
