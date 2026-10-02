from __future__ import annotations

from starlette.requests import Request

from app.config import RateLimit
from app.security import rate_limit
from app.security.csrf import new_token, same_origin, tokens_match
from app.security.rate_limit import SlidingWindowRateLimiter


def _request(headers: dict[str, str], scheme: str = "https") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": scheme,
        "server": ("forms.example", 443),
        "path": "/admin/logout",
        "query_string": b"",
        "headers": [(b"host", b"forms.example")]
        + [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def test_csrf_tokens() -> None:
    token = new_token()
    assert len(token) >= 40
    assert new_token() != token
    assert tokens_match(token, token)
    assert not tokens_match(token, token[:-1] + "x")
    assert not tokens_match(token, None)
    assert not tokens_match(None, token)
    assert not tokens_match("", "")


def test_same_origin_checks() -> None:
    assert same_origin(_request({}))
    assert same_origin(_request({"Origin": "https://forms.example"}))
    assert same_origin(_request({"Sec-Fetch-Site": "same-origin"}))
    assert not same_origin(_request({"Origin": "https://evil.example"}))
    assert not same_origin(_request({"Origin": "http://forms.example"}))
    assert not same_origin(_request({"Sec-Fetch-Site": "cross-site"}))
    assert not same_origin(_request({"Sec-Fetch-Site": "same-site"}))


def test_sliding_window_limits_and_recovers() -> None:
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    rule = RateLimit(2, 60)
    assert limiter.hit("b", "198.51.100.1", rule).allowed
    assert limiter.hit("b", "198.51.100.1", rule).allowed
    blocked = limiter.hit("b", "198.51.100.1", rule)
    assert not blocked.allowed and blocked.retry_after == 60
    assert limiter.hit("b", "198.51.100.2", rule).allowed, "keys are independent"
    assert limiter.hit("other", "198.51.100.1", rule).allowed, "buckets are independent"
    now[0] = 61
    assert limiter.hit("b", "198.51.100.1", rule).allowed


def test_stale_keys_are_swept() -> None:
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    rule = RateLimit(5, 60)
    for i in range(10):
        limiter.hit("b", f"198.51.100.{i}", rule)
    assert limiter.tracked_keys() == 10
    now[0] = rate_limit.STALE_AFTER_SECONDS + rate_limit.SWEEP_INTERVAL_SECONDS + 1
    limiter.hit("b", "203.0.113.1", rule)
    assert limiter.tracked_keys() == 1
