from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware

LIMIT = 1024


async def echo(request: Request) -> PlainTextResponse:
    body = await request.body()
    return PlainTextResponse(f"{len(body)}", headers={"Server": "leaky", "Cache-Control": "public"})


def _client(base_url: str = "http://testserver") -> TestClient:
    app = Starlette(routes=[Route("/echo", echo, methods=["GET", "POST"])])
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=LIMIT)
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app, base_url=base_url)


def test_security_headers() -> None:
    h = _client().get("/echo").headers
    csp = h["content-security-policy"]
    for directive in ("default-src 'none'", "script-src 'self'", "frame-ancestors 'none'"):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "same-origin"
    assert "geolocation=()" in h["permissions-policy"]
    assert h["cache-control"] == "no-store"
    assert "server" not in h
    assert "strict-transport-security" not in h, "HSTS only over HTTPS"


def test_hsts_over_https() -> None:
    h = _client("https://testserver").get("/echo").headers
    assert h["strict-transport-security"] == "max-age=15552000"


def test_body_within_limit_passes() -> None:
    res = _client().post("/echo", content=b"a" * LIMIT)
    assert res.status_code == 200 and res.text == str(LIMIT)


def test_declared_content_length_over_limit_is_413() -> None:
    res = _client().post("/echo", content=b"a" * (LIMIT + 1))
    assert res.status_code == 413
    assert res.json() == {
        "error": {"code": "PAYLOAD_TOO_LARGE", "message": "La petición es demasiado grande."}
    }
    assert res.headers["x-content-type-options"] == "nosniff"


def test_streamed_body_over_limit_is_413() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(4):
            yield b"a" * 512

    res = _client().post("/echo", content=chunks())
    assert "content-length" not in res.request.headers
    assert res.status_code == 413


def test_invalid_content_length_is_400() -> None:
    res = _client().post("/echo", content=b"x", headers={"Content-Length": "nope"})
    assert res.status_code == 400
