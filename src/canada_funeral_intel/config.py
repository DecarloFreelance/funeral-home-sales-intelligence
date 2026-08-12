from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    log_level: str
    http_user_agent: str
    http_timeout_seconds: int
    request_delay_seconds: float
    max_concurrency: int

    def as_display_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["database_path"] = str(self.database_path)
        return values


def _parse_int(env: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}, got {value}")
    return value


def _parse_float(
    env: Mapping[str, str], name: str, default: float, *, minimum: float
) -> float:
    raw = env.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}, got {value}")
    return value


def _parse_log_level(env: Mapping[str, str]) -> str:
    value = env.get("LOG_LEVEL", "INFO").strip().upper()
    if value not in logging.getLevelNamesMapping():
        raise ConfigurationError(f"LOG_LEVEL is invalid: {value!r}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    database_path_raw = source.get(
        "DATABASE_PATH",
        "database/sqlite/funeral_homes.sqlite3",
    ).strip()
    if not database_path_raw:
        raise ConfigurationError("DATABASE_PATH must not be empty")

    user_agent = source.get("HTTP_USER_AGENT", "CanadaFuneralIntel/0.1").strip()
    if not user_agent:
        raise ConfigurationError("HTTP_USER_AGENT must not be empty")

    return Settings(
        database_path=Path(database_path_raw).expanduser(),
        log_level=_parse_log_level(source),
        http_user_agent=user_agent,
        http_timeout_seconds=_parse_int(source, "HTTP_TIMEOUT_SECONDS", 20, minimum=1),
        request_delay_seconds=_parse_float(
            source, "REQUEST_DELAY_SECONDS", 1.0, minimum=0.0
        ),
        max_concurrency=_parse_int(source, "MAX_CONCURRENCY", 5, minimum=1),
    )
