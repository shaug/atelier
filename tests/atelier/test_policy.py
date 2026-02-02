import atelier.policy as policy


def test_build_combined_policy_with_split() -> None:
    combined, split = policy.build_combined_policy("planner text", "worker text")
    assert split is True
    assert "<!-- planner -->" in combined
    assert "<!-- worker -->" in combined


def test_split_combined_policy_sections() -> None:
    combined = "\n".join(
        [
            "<!-- planner -->",
            "planner line",
            "",
            "<!-- worker -->",
            "worker line",
            "",
        ]
    )
    sections = policy.split_combined_policy(combined)
    assert sections is not None
    assert sections[policy.ROLE_PLANNER] == "planner line"
    assert sections[policy.ROLE_WORKER] == "worker line"
