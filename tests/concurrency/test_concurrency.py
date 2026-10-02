"""Concurrency guarantees that exist in Hito 0.

Exclusive-value, reservation and partial-rollback races belong to the Submissions/Rules
milestone and are deferred there.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import RateLimit, Settings
from app.db.session import build_engine, build_session_factory
from app.main import create_app
from app.models import AdminSession
from app.security.rate_limit import SlidingWindowRateLimiter
from tests.conftest import admin_login


def test_rate_limiter_admits_exactly_limit_under_contention() -> None:
    limiter = SlidingWindowRateLimiter()
    rule = RateLimit(10, 60)
    barrier = threading.Barrier(50)

    def attempt(_: int) -> bool:
        barrier.wait()
        return limiter.hit("admin_login", "198.51.100.1", rule).allowed

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(attempt, range(50)))
    assert results.count(True) == 10


def test_concurrent_logins_get_distinct_valid_sessions(
    engine: Engine, settings_factory: Callable[..., Settings]
) -> None:
    app = create_app(settings_factory())
    clients = [TestClient(app) for _ in range(8)]
    barrier = threading.Barrier(len(clients))

    def login(client: TestClient) -> int:
        client.get("/admin/login")
        barrier.wait()
        return admin_login(client).status_code

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        statuses = list(pool.map(login, clients))
    assert statuses == [303] * len(clients)
    tokens = {c.cookies.get("fm_admin_session") for c in clients}
    assert len(tokens) == len(clients)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(AdminSession)) == len(clients)
    for client in clients:
        assert client.get("/admin", follow_redirects=False).status_code == 200


def test_lock_wait_is_bounded_by_lock_timeout(
    engine: Engine, settings_factory: Callable[..., Settings]
) -> None:
    with Session(engine) as s:
        s.add(
            AdminSession(
                token_hash="a" * 64,
                username="alice-example",
                csrf_token="c" * 43,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        s.commit()
    app_engine = build_engine(settings_factory(db_lock_timeout_ms=300))
    factory = build_session_factory(app_engine)
    holder = engine.connect()
    tx = holder.begin()
    try:
        holder.execute(
            text("SELECT 1 FROM admin_sessions WHERE token_hash = :h FOR UPDATE"), {"h": "a" * 64}
        )
        started = time.monotonic()
        with factory() as session, pytest.raises(OperationalError) as err:
            session.execute(delete(AdminSession).where(AdminSession.token_hash == "a" * 64))
            session.commit()
        assert time.monotonic() - started < 5
        assert getattr(err.value.orig, "sqlstate", None) == "55P03"  # lock_not_available
    finally:
        tx.rollback()
        holder.close()
        app_engine.dispose()


def test_slow_statement_is_bounded_by_statement_timeout(
    engine: Engine, settings_factory: Callable[..., Settings]
) -> None:
    app_engine = build_engine(settings_factory(db_statement_timeout_ms=300))
    try:
        with app_engine.connect() as conn, pytest.raises(OperationalError) as err:
            conn.execute(text("SELECT pg_sleep(3)"))
        assert getattr(err.value.orig, "sqlstate", None) == "57014"  # query_canceled
    finally:
        app_engine.dispose()
