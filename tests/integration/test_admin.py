from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, AdminSession
from tests.conftest import ADMIN_PASSWORD, ADMIN_USER, admin_csrf, admin_login, csrf_from

COOKIE = "fm_admin_session"


def set_session_cookie(client: TestClient, value: str) -> None:
    client.cookies.delete(COOKIE)
    client.cookies.set(COOKIE, value, domain="testserver.local")


def audit(engine: Engine) -> list[tuple[str, dict[str, object]]]:
    with Session(engine) as s:
        rows = s.scalars(select(AdminAuditLog).order_by(AdminAuditLog.id))
        return [(r.action, r.details) for r in rows]


def test_login_success(client: TestClient, engine: Engine) -> None:
    res = admin_login(client)
    assert res.status_code == 303 and res.headers["location"] == "/admin"
    page = client.get("/admin")
    assert page.status_code == 200
    assert "FormManager Admin" in page.text and "Saludable" in page.text
    assert re.search(r"Formularios cargados</dt>\s*<dd>0<", page.text)
    assert audit(engine) == [("ADMIN_LOGIN", {"admin": ADMIN_USER})]


def test_db_stores_only_token_hmac(client: TestClient, engine: Engine) -> None:
    admin_login(client)
    token = client.cookies.get(COOKIE)
    assert token
    with Session(engine) as s:
        stored = s.scalars(select(AdminSession.token_hash)).one()
    assert stored != token and token not in stored
    assert re.fullmatch(r"[0-9a-f]{64}", stored)


def test_login_wrong_password(client: TestClient, engine: Engine) -> None:
    res = admin_login(client, password="incorrect-password")
    assert res.status_code == 401
    assert "Usuario o contraseña incorrectos." in res.text
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert audit(engine) == [("ADMIN_LOGIN_FAILED", {})], "no username or password in audit"


def test_login_wrong_username(client: TestClient) -> None:
    assert admin_login(client, username="bob-example", password=ADMIN_PASSWORD).status_code == 401


def test_access_without_session(client: TestClient) -> None:
    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/admin/login"
    assert client.post("/admin/logout", data={"csrf_token": "x"}).status_code == 401
    set_session_cookie(client, "forged-token-value")
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_logged_in_user_skips_login_form(client: TestClient) -> None:
    admin_login(client)
    res = client.get("/admin/login", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/admin"


def test_logout_revokes_server_side(client: TestClient, engine: Engine) -> None:
    admin_login(client)
    token = client.cookies.get(COOKIE)
    res = client.post(
        "/admin/logout", data={"csrf_token": admin_csrf(client)}, follow_redirects=False
    )
    assert res.status_code == 303 and res.headers["location"] == "/admin/login"
    with Session(engine) as s:
        assert s.scalar(select(AdminSession)) is None
    set_session_cookie(client, token)
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert [a for a, _ in audit(engine)] == ["ADMIN_LOGIN", "ADMIN_LOGOUT"]


def test_session_regenerated_on_login(client: TestClient) -> None:
    admin_login(client)
    first = client.cookies.get(COOKIE)
    relogin = client.post(
        "/admin/login",
        data={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "csrf_token": _login_token(client),
        },
        follow_redirects=False,
    )
    assert relogin.status_code == 303
    second = client.cookies.get(COOKIE)
    assert first and second and first != second
    set_session_cookie(client, first)
    assert client.get("/admin", follow_redirects=False).status_code == 303, "old session is dead"


def _login_token(client: TestClient) -> str:
    """Login form token for a browser that is already logged in (the form itself redirects)."""
    saved = client.cookies.get(COOKIE)
    client.cookies.delete(COOKIE)
    token = csrf_from(client.get("/admin/login").text)
    if saved:
        set_session_cookie(client, saved)
    return token


def test_session_expires_server_side(client: TestClient, engine: Engine) -> None:
    admin_login(client)
    assert client.get("/admin", follow_redirects=False).status_code == 200
    with Session(engine) as s:
        s.execute(update(AdminSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_login_csrf_required(client: TestClient, engine: Engine) -> None:
    creds = {"username": ADMIN_USER, "password": ADMIN_PASSWORD}
    assert client.post("/admin/login", data=creds).status_code == 403
    assert client.post("/admin/login", data={**creds, "csrf_token": "forged"}).status_code == 403
    token = csrf_from(client.get("/admin/login").text)
    for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        res = client.post("/admin/login", data={**creds, "csrf_token": token}, headers=headers)
        assert res.status_code == 403, headers
    assert client.cookies.get(COOKIE) is None
    assert audit(engine) == []


def test_login_csrf_is_bound_to_cookie(client_factory: Callable[..., TestClient]) -> None:
    victim, attacker = client_factory(), client_factory()
    attacker_token = csrf_from(attacker.get("/admin/login").text)
    victim.get("/admin/login")
    res = victim.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "csrf_token": attacker_token},
    )
    assert res.status_code == 403


def test_logout_csrf_and_origin(client: TestClient, engine: Engine) -> None:
    admin_login(client)
    assert client.post("/admin/logout").status_code == 403
    assert client.post("/admin/logout", data={"csrf_token": "forged"}).status_code == 403
    token = admin_csrf(client)
    for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        res = client.post("/admin/logout", data={"csrf_token": token}, headers=headers)
        assert res.status_code == 403, headers
    with Session(engine) as s:
        assert s.scalar(select(AdminSession)) is not None, "session survives rejected logouts"


def test_login_rate_limit(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(admin_login_rate_limit="5/15minutes")
    for _ in range(5):
        assert admin_login(client, password="wrong-password").status_code == 401
    blocked = admin_login(client)
    assert blocked.status_code == 429, "even the right password is refused while blocked"
    assert 0 < int(blocked.headers["retry-after"]) <= 900


def test_spoofed_forwarded_for_does_not_bypass_rate_limit(
    client_factory: Callable[..., TestClient],
) -> None:
    client = client_factory(admin_login_rate_limit="2/15minutes")
    for i in range(2):
        admin_login(client, password="wrong", headers={"X-Forwarded-For": f"203.0.113.{i}"})
    blocked = admin_login(client, headers={"X-Forwarded-For": "203.0.113.99"})
    assert blocked.status_code == 429


def test_production_cookies_and_hsts(client_factory: Callable[..., TestClient]) -> None:
    client = client_factory(base_url="https://testserver", app_env="production")
    page = client.get("/admin/login")
    assert "max-age=15552000" in page.headers["strict-transport-security"]
    login_cookie = page.headers["set-cookie"].lower()
    assert login_cookie.startswith("__host-fm_login_csrf=")
    res = client.post(
        "/admin/login",
        data={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "csrf_token": csrf_from(page.text),
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    cookie = next(
        c for c in res.headers.get_list("set-cookie") if c.startswith(f"__Host-{COOKIE}=")
    )
    lowered = cookie.lower()
    for attr in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attr in lowered
    assert "domain=" not in lowered
    assert client.get("/admin").status_code == 200


def test_login_input_is_escaped(client: TestClient) -> None:
    payload = "<script>alert(1)</script>"
    res = admin_login(client, username=payload, password="x")
    assert res.status_code == 401
    assert payload not in res.text and "&lt;script&gt;" in res.text


def test_oversized_field_is_rejected_without_echo(client: TestClient) -> None:
    token = csrf_from(client.get("/admin/login").text)
    long_name = "carol-example-" + "z" * 300
    res = client.post(
        "/admin/login", data={"username": long_name, "password": "x", "csrf_token": token}
    )
    assert res.status_code == 422
    assert long_name not in res.text and "Traceback" not in res.text


def test_request_too_large(client: TestClient) -> None:
    res = client.post(
        "/admin/login",
        content=b"a" * 20000,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 413
