from __future__ import annotations

import hmac
import secrets

from starlette.requests import Request

CSRF_FORM_FIELD = "csrf_token"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def tokens_match(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def same_origin(request: Request) -> bool:
    """Reject cross-site requests using Sec-Fetch-Site and Origin when the browser sends them."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    expected = f"{request.url.scheme}://{request.url.netloc}"
    return hmac.compare_digest(origin.encode(), expected.encode())
