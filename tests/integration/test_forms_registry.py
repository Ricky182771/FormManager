"""forms_registry against real PostgreSQL: migration 0002 and filesystem -> registry sync."""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import Settings
from app.forms.catalog import FormCatalog
from app.forms.loader import scan_forms_dir
from app.forms.package import FormPackage
from app.forms.registry import sync_registry
from app.main import create_app
from tests.conftest import TEST_DATABASE_URL, UNREACHABLE_DATABASE_URL, alembic_config
from tests.forms_fixtures import FORM_A, FORM_B, FORM_C, form_toml, write_package

MAX = 64 * 1024


def rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM forms_registry ORDER BY id"))
        return [dict(r._mapping) for r in result]


def loaded(root: Path) -> tuple[FormPackage, ...]:
    return scan_forms_dir(root, MAX).forms


@pytest.fixture
def catalog(forms_root: Path, session_factory: sessionmaker[Session]) -> FormCatalog:
    def sync(forms: tuple[FormPackage, ...]) -> None:
        sync_registry(session_factory, forms)

    return FormCatalog(forms_root, MAX, sync)


def test_migration_0002_upgrade_creates_registry(engine: Engine) -> None:
    insp = inspect(engine)
    columns = {c["name"] for c in insp.get_columns("forms_registry")}
    assert columns == {
        "id",
        "slug",
        "relative_path",
        "schema_version",
        "title",
        "status",
        "updated_at",
    }
    assert insp.get_pk_constraint("forms_registry")["name"] == "pk_forms_registry"
    assert [u["name"] for u in insp.get_unique_constraints("forms_registry")] == [
        "uq_forms_registry_slug"
    ]
    checks = {c["name"] for c in insp.get_check_constraints("forms_registry")}
    assert checks == {
        "ck_forms_registry_id_format",
        "ck_forms_registry_slug_format",
        "ck_forms_registry_status_valid",
        "ck_forms_registry_relative_path_relative",
        "ck_forms_registry_schema_version_positive",
    }


def test_migration_0002_downgrade_and_upgrade(engine: Engine) -> None:
    cfg = alembic_config(make_url(TEST_DATABASE_URL))
    command.downgrade(cfg, "0001")
    try:
        tables = set(inspect(engine).get_table_names())
        assert "forms_registry" not in tables and "admin_sessions" in tables
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    finally:
        command.upgrade(cfg, "head")
    assert "forms_registry" in inspect(engine).get_table_names()


def test_sync_inserts_valid_forms(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "contact", title="Contacto")
    result = sync_registry(session_factory, loaded(forms_root))
    assert (result.inserted, result.updated, result.deleted) == (2, 0, 0)
    assert [
        (r["id"], r["slug"], r["title"], r["status"], r["schema_version"]) for r in rows(engine)
    ] == [
        (FORM_A, "room-booking", "Reserva de sala", "draft", 1),
        (FORM_B, "contact", "Contacto", "draft", 1),
    ]


def test_sync_is_idempotent(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    sync_registry(session_factory, loaded(forms_root))
    before = rows(engine)
    result = sync_registry(session_factory, loaded(forms_root))
    assert (result.inserted, result.updated, result.deleted) == (0, 0, 0)
    assert rows(engine) == before  # updated_at included: nothing rewritten


def test_sync_updates_changed_metadata(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    package = write_package(forms_root, FORM_A, "room-booking")
    sync_registry(session_factory, loaded(forms_root))
    [before] = rows(engine)
    (package / "form.toml").write_text(
        form_toml(FORM_A, "room-booking-v2", "Reserva de sala grande").replace("draft", "open")
    )
    result = sync_registry(session_factory, loaded(forms_root))
    assert (result.inserted, result.updated, result.deleted) == (0, 1, 0)
    [after] = rows(engine)
    assert (after["slug"], after["title"], after["status"]) == (
        "room-booking-v2",
        "Reserva de sala grande",
        "open",
    )
    assert after["updated_at"] >= before["updated_at"]


def test_updated_at_is_postgres_time_and_only_moves_on_real_change(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    package = write_package(forms_root, FORM_A, "room-booking")
    sync_registry(session_factory, loaded(forms_root))
    past = datetime(2020, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(text("UPDATE forms_registry SET updated_at = :t"), {"t": past})

    sync_registry(session_factory, loaded(forms_root))
    [unchanged] = rows(engine)
    assert unchanged["updated_at"] == past

    (package / "form.toml").write_text(form_toml(FORM_A, "room-booking", "Reserva de sala B"))
    sync_registry(session_factory, loaded(forms_root))
    [changed] = rows(engine)
    with engine.connect() as conn:
        db_now = conn.scalar(text("SELECT now()"))
    assert changed["updated_at"].tzinfo is not None
    assert past < changed["updated_at"] <= db_now
    assert db_now - changed["updated_at"] < timedelta(seconds=30)


def test_sync_handles_slug_swap_between_forms(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    a = write_package(forms_root, FORM_A, "first")
    b = write_package(forms_root, FORM_B, "second")
    sync_registry(session_factory, loaded(forms_root))
    (a / "form.toml").write_text(form_toml(FORM_A, "second"))
    (b / "form.toml").write_text(form_toml(FORM_B, "first"))
    sync_registry(session_factory, loaded(forms_root))
    assert [(r["id"], r["slug"]) for r in rows(engine)] == [(FORM_A, "second"), (FORM_B, "first")]


def test_sync_removes_forms_that_disappear(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "contact")
    sync_registry(session_factory, loaded(forms_root))
    shutil.rmtree(forms_root / FORM_A)
    result = sync_registry(session_factory, loaded(forms_root))
    assert result.deleted == 1
    assert [r["id"] for r in rows(engine)] == [FORM_B]


def test_invalid_form_is_removed_and_never_inserted(
    engine: Engine, catalog: FormCatalog, forms_root: Path
) -> None:
    package = write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "broken", form="= = =")
    catalog.reload()
    assert [r["id"] for r in rows(engine)] == [FORM_A]
    (package / "rules.json").write_text("[]")
    catalog.reload()
    assert rows(engine) == []


def test_duplicate_slugs_on_disk_register_neither(
    engine: Engine, catalog: FormCatalog, forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "room-booking")
    write_package(forms_root, FORM_C, "contact")
    catalog.reload()
    assert [r["id"] for r in rows(engine)] == [FORM_C]


def test_unique_slug_constraint(engine: Engine) -> None:
    insert = text(
        "INSERT INTO forms_registry (id, slug, relative_path, schema_version, title, status) "
        "VALUES (:id, 'same', :id, 1, 'Reserva de sala', 'draft')"
    )
    with pytest.raises(IntegrityError) as exc, engine.begin() as conn:
        conn.execute(insert, {"id": FORM_A})
        conn.execute(insert, {"id": FORM_B})
    assert "uq_forms_registry_slug" in str(exc.value)


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("relative_path", "/data/forms/AAAAAAAAAAAAAAAA", "relative_path_relative"),
        ("relative_path", "../AAAAAAAAAAAAAAAA", "relative_path_relative"),
        ("id", "../../etc/passwd", "id_format"),
        ("slug", "Bad Slug", "slug_format"),
        ("status", "published", "status_valid"),
    ],
)
def test_check_constraints(engine: Engine, column: str, value: str, constraint: str) -> None:
    values = {
        "id": FORM_A,
        "slug": "room-booking",
        "relative_path": FORM_A,
        "status": "draft",
    } | {column: value}
    with pytest.raises(IntegrityError) as exc, engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO forms_registry (id, slug, relative_path, schema_version, title, status)"
                " VALUES (:id, :slug, :relative_path, 1, 'Reserva de sala', :status)"
            ),
            values,
        )
    assert f"ck_forms_registry_{constraint}" in str(exc.value)


def test_sync_failure_rolls_back_everything(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    sync_registry(session_factory, loaded(forms_root))
    before = rows(engine)
    [form_a] = loaded(forms_root)
    # Bypasses the loader's duplicate check, so the deferred unique constraint fails at COMMIT,
    # after the delete and inserts already ran inside the transaction.
    clash = [
        dataclasses.replace(form_a, id=FORM_B, relative_path=FORM_B, slug="contact"),
        dataclasses.replace(form_a, id=FORM_C, relative_path=FORM_C, slug="contact"),
    ]
    with pytest.raises(IntegrityError):
        sync_registry(session_factory, clash)
    assert rows(engine) == before


def test_db_failure_during_reload_is_not_reported_as_invalid_form(
    forms_root: Path, settings_factory: Callable[..., Settings], engine: Engine
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    app = create_app(settings_factory(database_url=UNREACHABLE_DATABASE_URL))
    catalog: FormCatalog = app.state.services.catalog
    with pytest.raises(OperationalError):
        catalog.reload()
    assert catalog.count == 0 and catalog.diagnostics == ()
    with pytest.raises(OperationalError), TestClient(app):
        pass  # startup aborts: filesystem and registry would diverge


def test_no_absolute_paths_persisted(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "contact")
    sync_registry(session_factory, loaded(forms_root))
    for row in rows(engine):
        assert row["relative_path"] == row["id"]
        assert str(forms_root) not in " ".join(str(v) for v in row.values())


def test_models_match_migrations(engine: Engine) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db.base import Base

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
