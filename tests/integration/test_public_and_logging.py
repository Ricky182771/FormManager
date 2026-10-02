from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.logging_setup import JsonFormatter
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, admin_csrf, admin_login, password_hash


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}


def test_root_reports_core_state(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "<h1>FormManager</h1>" in res.text
    assert "En ejecución" in res.text and "Saludable" in res.text
    assert re.search(r"Formularios cargados</dt>\s*<dd>0<", res.text)


def test_root_security_headers(client: TestClient) -> None:
    h = client.get("/").headers
    assert "default-src 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in h


def test_static_css_is_served_and_cacheable(client: TestClient) -> None:
    res = client.get("/static/css/app.css")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/css")
    assert res.headers.get("cache-control") != "no-store"


def test_incomplete_package_is_not_loaded_or_rendered(
    engine: Engine, settings_factory: Callable[..., Settings], forms_root: Path
) -> None:
    package = forms_root / "K8mP4qT2xN7rV5sA"
    package.mkdir()
    (package / "form.toml").write_text('title = "ALICE EXAMPLE form"\n')
    with TestClient(create_app(settings_factory())) as client:
        res = client.get("/")
    assert "ALICE EXAMPLE" not in res.text
    assert re.search(r"Formularios cargados</dt>\s*<dd>0<", res.text)


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_login_flow_leaks_no_secrets_to_logs(
    client: TestClient, captured_logs: io.StringIO
) -> None:
    admin_login(client, password="dave-example-wrong-password")
    admin_login(client)
    session_token = client.cookies.get("fm_admin_session")
    csrf = admin_csrf(client)
    client.post("/admin/logout", data={"csrf_token": csrf})
    output = captured_logs.getvalue()
    assert '"event": "request"' in output and '"event": "admin_action"' in output
    for secret in (
        ADMIN_PASSWORD,
        "dave-example-wrong-password",
        password_hash(ADMIN_PASSWORD),
        session_token,
        csrf,
        "s" * 48,
        "testclient",
    ):
        assert secret and secret not in output
