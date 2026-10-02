"""Block until PostgreSQL accepts connections, with exponential backoff and a hard deadline."""

from __future__ import annotations

import logging
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.logging_setup import configure_logging

logger = logging.getLogger("app.wait_for_db")


def main(timeout_seconds: float = 90.0) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.sqlalchemy_url, connect_args={"connect_timeout": 3})
    deadline = time.monotonic() + timeout_seconds
    delay = 0.5
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("database_ready", extra={"attempts": attempt})
            engine.dispose()
            return 0
        except OperationalError as exc:
            if time.monotonic() + delay > deadline:
                logger.error(
                    "database_unreachable",
                    extra={"attempts": attempt, "error_type": type(exc.orig).__name__},
                )
                return 1
            logger.info("database_waiting", extra={"attempt": attempt, "retry_in": delay})
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


if __name__ == "__main__":
    sys.exit(main())
