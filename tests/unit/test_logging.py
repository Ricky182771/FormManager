from __future__ import annotations

import json
import logging

from app.logging_setup import ALLOWED_EXTRAS, JsonFormatter, is_sensitive_key


def _format(extra: dict[str, object], msg: str = "event_name") -> dict[str, object]:
    record = logging.makeLogRecord({"name": "app.test", "levelname": "INFO", "msg": msg, **extra})
    return dict(json.loads(JsonFormatter().format(record)))


def test_core_fields_present() -> None:
    out = _format({})
    assert set(out) == {"timestamp", "level", "logger", "event"}
    assert out["event"] == "event_name" and out["logger"] == "app.test" and out["level"] == "INFO"
    assert str(out["timestamp"]).endswith("+00:00")


def test_allowlisted_extras_kept() -> None:
    out = _format({"method": "GET", "path": "/admin", "status": 200, "ms": 1.5})
    assert out["method"] == "GET" and out["status"] == 200


def test_secrets_never_logged() -> None:
    secrets = {
        "password": "alice-example-password-123",
        "password_hash": "$argon2id$v=19$abc",
        "secret": "s" * 48,
        "session_secret": "s" * 48,
        "token": "tok-value",
        "csrf": "csrf-value",
        "csrf_token": "csrf-value",
        "cookie": "fm_admin_session=abc",
        "authorization": "Bearer abc",
        "api_key": "key-value",
        "access_code": "code-value",
        "database_url": "postgresql://u:pw@db/x",
        "body": '{"answer": "x"}',
        "client_ip": "198.51.100.7",
        "username_attempt": "alice-example-password-123",
    }
    line = JsonFormatter().format(
        logging.makeLogRecord({"name": "app", "levelname": "INFO", "msg": "e", **secrets})
    )
    for value in secrets.values():
        assert value not in line


def test_allowlist_contains_no_sensitive_key() -> None:
    assert not [key for key in ALLOWED_EXTRAS if is_sensitive_key(key)]
