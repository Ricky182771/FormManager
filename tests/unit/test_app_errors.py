"""App-level behaviour that needs no database: the DB URL points at a closed port."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import StorageError
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


@pytest.fixture
def offline_app(tmp_path: Path) -> FastAPI:
    return create_app(make_settings(tmp_path, database_url=UNREACHABLE_DATABASE_URL))


@pytest.fixture
def offline(offline_app: FastAPI) -> TestClient:
    return TestClient(offline_app, raise_server_exceptions=False)


def test_app_title(offline_app: FastAPI) -> None:
    assert offline_app.title == "FormManager"


def test_health_reports_db_down_without_leaking(offline: TestClient) -> None:
    res = offline.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable", "database": "unavailable"}
    assert "not-a-real-password" not in res.text and "127.0.0.1" not in res.text


def test_root_shows_db_unavailable(offline: TestClient) -> None:
    res = offline.get("/")
    assert res.status_code == 200
    assert "No disponible" in res.text and "not-a-real-password" not in res.text


def test_api_namespace_is_reserved_and_returns_json(offline: TestClient) -> None:
    res = offline.get("/api/v1/forms/anything/definition")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"
    assert offline.post("/api/v1/forms/x/submissions", json={}).status_code == 404


def test_no_interactive_docs(offline: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert offline.get(path).status_code == 404


def test_no_cors(offline: TestClient) -> None:
    preflight = offline.options(
        "/admin/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_unhandled_error_has_no_stack_trace(offline_app: FastAPI, offline: TestClient) -> None:
    @offline_app.get("/api/v1/boom")
    def boom() -> None:
        raise RuntimeError("internal detail /srv/app/secret.py SELECT * FROM admin_sessions")

    res = offline.get("/api/v1/boom")
    assert res.status_code == 500
    assert res.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Ocurrió un error inesperado."}
    }
    for leak in ("Traceback", "RuntimeError", "SELECT", "/srv/app", "admin_sessions"):
        assert leak not in res.text


def test_db_error_on_admin_page_is_generic_503(offline: TestClient) -> None:
    offline.cookies.set("fm_admin_session", "t" * 43)
    res = offline.get("/admin", follow_redirects=False)
    assert res.status_code == 503
    assert "Traceback" not in res.text and "psycopg" not in res.text.lower()


def test_html_404_does_not_echo_path(offline: TestClient) -> None:
    payload = "<script>alert(1)</script>"
    res = offline.get("/missing-" + payload)
    assert res.status_code == 404 and payload not in res.text


def test_unusable_forms_dir_blocks_startup(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "forms"
    not_a_dir.write_text("x")
    with pytest.raises(StorageError):
        create_app(make_settings(not_a_dir, database_url=UNREACHABLE_DATABASE_URL))
