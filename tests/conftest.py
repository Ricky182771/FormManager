from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from app.config import Settings
from app.main import create_app
from app.security.passwords import hash_secret

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://formmanager_test_app:test_app@127.0.0.1:55433/formmanager_test",
)
# Nothing listens on port 1, so connections fail immediately: used by tests that need no DB.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody:not-a-real-password@127.0.0.1:1/none"

ADMIN_USER = "alice-example"
ADMIN_PASSWORD = "alice-example-password-123"

_HASHES: dict[str, str] = {}
_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


def password_hash(value: str) -> str:
    """Argon2 is slow on purpose; hash each test password once per run."""
    if value not in _HASHES:
        _HASHES[value] = hash_secret(value)
    return _HASHES[value]


def alembic_config(url: URL) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture
def forms_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # Per test: the catalog scans this directory, so packages must not leak between tests.
    return tmp_path_factory.mktemp("forms")


def make_settings(forms_dir: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "database_url": TEST_DATABASE_URL,
        "forms_dir": forms_dir,
        "session_secret": "s" * 48,
        "admin_username": ADMIN_USER,
        "admin_password_hash": password_hash(ADMIN_PASSWORD),
        "admin_login_rate_limit": "1000/1minute",
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = make_url(TEST_DATABASE_URL)
    eng = create_engine(url, pool_size=20, max_overflow=10)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.exit(
            f"Test PostgreSQL unavailable ({type(exc).__name__}). Run: make test-db-up",
            returncode=3,
        )
    # The app role owns the schema, so it can reset it without superuser rights.
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(url), "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_db(request: pytest.FixtureRequest) -> Iterator[None]:
    if "engine" not in request.fixturenames:
        yield
        return
    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(
            text("TRUNCATE admin_sessions, admin_audit_log, forms_registry RESTART IDENTITY")
        )
    yield


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def settings_factory(forms_root: Path) -> Callable[..., Settings]:
    def build(**overrides: object) -> Settings:
        return make_settings(forms_root, **overrides)

    return build


@pytest.fixture
def app(engine: Engine, settings_factory: Callable[..., Settings]) -> FastAPI:
    return create_app(settings_factory())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Context manager runs the lifespan: catalog load + registry sync, as in production.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory(
    engine: Engine, settings_factory: Callable[..., Settings]
) -> Callable[..., TestClient]:
    def build(base_url: str = "http://testserver", **overrides: object) -> TestClient:
        return TestClient(create_app(settings_factory(**overrides)), base_url=base_url)

    return build


def csrf_from(html: str) -> str:
    match = _CSRF_FIELD.search(html)
    assert match, "no CSRF field on page"
    return match.group(1)


def admin_login(
    client: TestClient,
    username: str = ADMIN_USER,
    password: str = ADMIN_PASSWORD,
    headers: dict[str, str] | None = None,
) -> Response:
    token = csrf_from(client.get("/admin/login").text)
    return client.post(
        "/admin/login",
        data={"username": username, "password": password, "csrf_token": token},
        headers=headers,
        follow_redirects=False,
    )


def admin_csrf(client: TestClient) -> str:
    page = client.get("/admin", follow_redirects=False)
    assert page.status_code == 200, page.status_code
    return csrf_from(page.text)
