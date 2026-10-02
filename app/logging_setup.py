from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

# Only these extra={} keys reach the output; anything else is dropped before serialisation.
ALLOWED_EXTRAS = frozenset(
    {
        "action",
        "admin",
        "admin_enabled",
        "attempt",
        "attempts",
        "db_reachable",
        "detail",
        "env",
        "error_code",
        "error_type",
        "file",
        "form_id",
        "forms_invalid",
        "forms_valid",
        "method",
        "ms",
        "path",
        "registry_deleted",
        "registry_inserted",
        "registry_updated",
        "relative_path",
        "retry_in",
        "slug",
        "status",
    }
)

# Second line of defence: a key containing any of these fragments is never logged,
# even if someone adds it to the allowlist by mistake.
SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "csrf",
    "cookie",
    "authorization",
    "api_key",
    "apikey",
    "access_code",
    "database_url",
    "dsn",
    "hash",
    "body",
    "env_file",
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS)


class JsonFormatter(logging.Formatter):
    """One JSON object per line with timestamp, level, logger, event and allowlisted extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if key not in ALLOWED_EXTRAS or is_sensitive_key(key):
                continue
            payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn access logs would persist client IPs; RequestLogMiddleware logs requests without them.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").handlers[:] = []
    logging.getLogger("uvicorn.error").propagate = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
