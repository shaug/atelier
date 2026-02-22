from atelier import cli_defaults


def test_work_cli_env_defaults_include_expected_mappings() -> None:
    by_flag = {item.flag: item for item in cli_defaults.WORK_CLI_ENV_DEFAULTS}
    assert by_flag["--mode"].env_var == "ATELIER_MODE"
    assert by_flag["--run-mode"].env_var == "ATELIER_RUN_MODE"
    assert by_flag["--watch-interval-seconds"].env_var == "ATELIER_WATCH_INTERVAL"
    assert by_flag["--yes"].env_var == "ATELIER_WORK_YES"


def test_resolve_work_yes_default_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_WORK_YES", "yes")
    resolved = cli_defaults.resolve_work_yes_default(False)

    assert resolved.source == "env"
    assert resolved.value is True


def test_resolve_work_yes_default_prefers_cli(monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_WORK_YES", "0")
    resolved = cli_defaults.resolve_work_yes_default(True)

    assert resolved.source == "cli"
    assert resolved.value is True


def test_resolve_work_watch_interval_default_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_WATCH_INTERVAL", "12")
    resolved = cli_defaults.resolve_work_watch_interval_default()

    assert resolved.source == "env"
    assert resolved.value == 12


def test_describe_translated_default_mentions_env_and_flag() -> None:
    resolved = cli_defaults.ResolvedCliDefault(
        flag="--mode",
        value="auto",
        source="env",
        env_var="ATELIER_MODE",
        raw_env_value="AUTO",
    )

    message = cli_defaults.describe_translated_default(resolved)
    assert "ATELIER_MODE='AUTO'" in message
    assert "--mode='auto'" in message
