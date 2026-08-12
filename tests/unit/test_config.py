from pathlib import Path

import pytest

from canada_funeral_intel.config import ConfigurationError, load_settings


def test_default_configuration() -> None:
    settings = load_settings({})
    assert settings.database_path == Path("database/sqlite/funeral_homes.sqlite3")
    assert settings.log_level == "INFO"
    assert settings.http_user_agent == "CanadaFuneralIntel/0.1"
    assert settings.http_timeout_seconds == 20
    assert settings.request_delay_seconds == 1.0
    assert settings.max_concurrency == 5


def test_environment_overrides() -> None:
    settings = load_settings(
        {
            "DATABASE_PATH": "~/funeral/test.sqlite3",
            "LOG_LEVEL": "debug",
            "HTTP_USER_AGENT": "TestAgent/1.0",
            "HTTP_TIMEOUT_SECONDS": "30",
            "REQUEST_DELAY_SECONDS": "0.25",
            "MAX_CONCURRENCY": "9",
        }
    )
    assert settings.database_path == Path("~/funeral/test.sqlite3").expanduser()
    assert settings.log_level == "DEBUG"
    assert settings.http_user_agent == "TestAgent/1.0"
    assert settings.http_timeout_seconds == 30
    assert settings.request_delay_seconds == 0.25
    assert settings.max_concurrency == 9


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HTTP_TIMEOUT_SECONDS", "abc"),
        ("MAX_CONCURRENCY", "1.5"),
        ("REQUEST_DELAY_SECONDS", "later"),
    ],
)
def test_invalid_numeric_values(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({name: value})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HTTP_TIMEOUT_SECONDS", "0"),
        ("MAX_CONCURRENCY", "0"),
        ("REQUEST_DELAY_SECONDS", "-0.1"),
    ],
)
def test_invalid_ranges(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        load_settings({name: value})


def test_invalid_log_level() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"LOG_LEVEL": "LOUD"})


def test_blank_required_strings() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({"DATABASE_PATH": "   "})
    with pytest.raises(ConfigurationError):
        load_settings({"HTTP_USER_AGENT": "   "})
