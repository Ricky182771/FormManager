from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import RateLimit, Settings

PROD_OK: dict[str, object] = {
    "app_env": "production",
    "session_secret": "x" * 40,
    "app_db_password": "p@ss/word",
}


def test_production_rejects_short_session_secret() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(**{**PROD_OK, "session_secret": "short"})  # type: ignore[arg-type]


def test_production_rejects_missing_session_secret() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(app_env="production", app_db_password="p")


def test_production_rejects_missing_db_credentials() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL or APP_DB_PASSWORD"):
        Settings(app_env="production", session_secret="x" * 40)


def test_production_rejects_half_configured_admin() -> None:
    with pytest.raises(ValidationError, match="ADMIN_USERNAME and ADMIN_PASSWORD_HASH"):
        Settings(**{**PROD_OK, "admin_username": "alice-example"})  # type: ignore[arg-type]


def test_production_valid_settings_hide_secrets() -> None:
    ok = Settings(**PROD_OK)  # type: ignore[arg-type]
    assert ok.sqlalchemy_url.password == "p@ss/word"
    assert ok.sqlalchemy_url.username == "formmanager_app"
    assert "p@ss" not in repr(ok)
    assert "x" * 40 not in repr(ok)
    assert not ok.admin_enabled


def test_database_url_gets_psycopg_driver() -> None:
    s = Settings(app_env="test", database_url="postgresql://u:p@h:5432/d")
    assert s.sqlalchemy_url.drivername == "postgresql+psycopg"


def test_forms_dir_default_and_override(tmp_path: Path) -> None:
    assert Settings(app_env="test").forms_dir == Path("/data/forms")
    assert Settings(app_env="test", forms_dir=tmp_path).forms_dir == tmp_path


def test_forms_dir_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Settings(app_env="test", forms_dir=Path("relative/forms"))


@pytest.mark.parametrize(
    ("field", "value"),
    [("app_timezone", "Mars/Olympus"), ("log_level", "LOUD"), ("admin_login_rate_limit", "x")],
)
def test_invalid_values_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="test", **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "limit", "window"),
    [
        ("10/5minutes", 10, 300),
        ("5/15minutes", 5, 900),
        ("3/hour", 3, 3600),
        ("2/30seconds", 2, 30),
    ],
)
def test_rate_limit_parse(raw: str, limit: int, window: int) -> None:
    assert RateLimit.parse(raw) == RateLimit(limit, window)


@pytest.mark.parametrize("raw", ["", "10", "x/5minutes", "0/5minutes", "10/5days"])
def test_rate_limit_parse_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        RateLimit.parse(raw)
