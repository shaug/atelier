import atelier.branching as branching


def test_suggest_root_branch_appends_bead_id_suffix() -> None:
    branch = branching.suggest_root_branch(
        "Startup deterministic",
        "scott/",
        bead_id="at-uuzc",
    )

    assert branch == "scott/startup-deterministic-at-uuzc"


def test_suggest_root_branch_truncates_title_but_preserves_suffix() -> None:
    branch = branching.suggest_root_branch(
        "Make default epic root branches collision proof under startup assume yes mode",
        "",
        bead_id="at-ua3a",
        max_len=30,
    )

    assert branch.endswith("-at-ua3a")
    assert len(branch) <= 30
    assert branch.startswith("make-default-epic-root")


def test_suggest_root_branch_without_bead_id_matches_legacy_behavior() -> None:
    branch = branching.suggest_root_branch("Hello World", "scott/")

    assert branch == "scott/hello-world"
