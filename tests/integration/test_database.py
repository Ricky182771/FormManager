from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.config import Settings
from app.db.session import build_engine, build_session_factory, ping
from tests.conftest import TEST_DATABASE_URL, alembic_config

EXPECTED_TABLES = {"admin_sessions", "admin_audit_log", "alembic_version"}


def test_real_postgres_connection_and_ping(settings_factory: Callable[..., Settings]) -> None:
    engine = build_engine(settings_factory())
    try:
        assert ping(engine)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version()")).startswith("PostgreSQL")
    finally:
        engine.dispose()


def test_engine_session_settings(settings_factory: Callable[..., Settings], engine: Engine) -> None:
    app_engine = build_engine(settings_factory())
    try:
        with app_engine.connect() as conn:
            assert conn.scalar(text("SHOW application_name")) == "formmanager"
            assert conn.scalar(text("SHOW statement_timeout")) == "15s"
            assert conn.scalar(text("SHOW lock_timeout")) == "10s"
        session = build_session_factory(app_engine)()
        assert session.expire_on_commit is False
        session.close()
    finally:
        app_engine.dispose()


def test_migration_0001_creates_only_generic_tables(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0001"


def test_migration_0001_downgrade_and_upgrade(engine: Engine) -> None:
    cfg = alembic_config(make_url(TEST_DATABASE_URL))
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_constraint_names_follow_convention(engine: Engine) -> None:
    insp = inspect(engine)
    assert insp.get_pk_constraint("admin_sessions")["name"] == "pk_admin_sessions"
    assert insp.get_pk_constraint("admin_audit_log")["name"] == "pk_admin_audit_log"


def test_application_role_is_least_privilege(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    assert tuple(row) == (False, False, False, False, False)
