import pytest

from atelier import runtime_profiles


def test_normalize_runtime_profile_defaults_to_standard() -> None:
    assert runtime_profiles.normalize_runtime_profile(None, source="runtime") == "standard"


def test_normalize_runtime_profile_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        runtime_profiles.normalize_runtime_profile("bogus", source="runtime")
