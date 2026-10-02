from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*(second|minute|hour)s?\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, raw: str) -> RateLimit:
        """Parse values such as "10/5minutes", "5/15minute" or "3/hour"."""
        match = _RATE_RE.match(raw)
        if not match:
            raise ValueError(f"Invalid rate limit {raw!r} (example: 5/15minutes)")
        limit = int(match.group(1))
        amount = int(match.group(2) or 1)
        window = amount * _UNIT_SECONDS[match.group(3).lower()]
        if limit < 1 or window < 1:
            raise ValueError(f"Rate limit out of range: {raw!r}")
        return cls(limit=limit, window_seconds=window)


class Settings(BaseSettings):
    """Instance-level infrastructure settings. Per-form configuration never lives here."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["production", "development", "test"] = "production"
    app_timezone: str = "UTC"

    forms_dir: Path = Path("/data/forms")

    database_url: SecretStr | None = None
    postgres_db: str = "formmanager"
    app_db_user: str = "formmanager_app"
    app_db_password: SecretStr | None = None
    db_host: str = "db"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_statement_timeout_ms: int = Field(default=15000, ge=100, le=600_000)
    db_lock_timeout_ms: int = Field(default=10000, ge=100, le=600_000)

    admin_username: str = ""
    admin_password_hash: SecretStr | None = None
    session_secret: SecretStr = Field(default=SecretStr(""))

    admin_login_rate_limit: str = "5/15minutes"
    session_max_age_seconds: int = Field(default=4 * 3600, ge=300, le=24 * 3600)
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024, le=1024 * 1024)

    log_level: str = "INFO"

    @field_validator("admin_password_hash", "database_url", "app_db_password", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone {value!r}") from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return level

    @field_validator("forms_dir")
    @classmethod
    def _absolute_forms_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("FORMS_DIR must be an absolute path")
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        RateLimit.parse(self.admin_login_rate_limit)
        if self.app_env == "production":
            problems: list[str] = []
            if len(self.session_secret.get_secret_value()) < 32:
                problems.append("SESSION_SECRET must be at least 32 characters")
            if self.database_url is None and self.app_db_password is None:
                problems.append("set DATABASE_URL or APP_DB_PASSWORD")
            if bool(self.admin_username) != (self.admin_password_hash is not None):
                problems.append("ADMIN_USERNAME and ADMIN_PASSWORD_HASH must be set together")
            if problems:
                raise ValueError("Invalid configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_username) and self.admin_password_hash is not None

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def sqlalchemy_url(self) -> URL:
        if self.database_url is not None:
            url = make_url(self.database_url.get_secret_value())
            if url.drivername in ("postgresql", "postgres"):
                url = url.set(drivername="postgresql+psycopg")
            return url
        return URL.create(
            "postgresql+psycopg",
            username=self.app_db_user,
            password=self.app_db_password.get_secret_value() if self.app_db_password else None,
            host=self.db_host,
            port=self.db_port,
            database=self.postgres_db,
        )

    @property
    def admin_login_limit(self) -> RateLimit:
        return RateLimit.parse(self.admin_login_rate_limit)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
