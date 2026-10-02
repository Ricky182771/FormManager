from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings
from app.models import AdminSession
from app.security.csrf import new_token

MAX_TOKEN_LENGTH = 128
LOGIN_CSRF_MAX_AGE_SECONDS = 3600


def cookie_name(base: str, settings: Settings) -> str:
    # __Host- binds the cookie to this exact origin (Secure, Path=/, no Domain).
    return f"__Host-{base}" if settings.is_production else base


class LoginCsrfCodec:
    """Signed cookie holding the CSRF token of the login form, before any session exists."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._serializer = URLSafeTimedSerializer(
            settings.session_secret.get_secret_value(), salt="admin-login-csrf-v1"
        )
        self.cookie_name = cookie_name("fm_login_csrf", settings)

    def load(self, request: Request) -> str | None:
        raw = request.cookies.get(self.cookie_name)
        if not raw or len(raw) > 512:
            return None
        try:
            token = self._serializer.loads(raw, max_age=LOGIN_CSRF_MAX_AGE_SECONDS)
        except BadSignature:
            return None
        return token if isinstance(token, str) and len(token) >= 32 else None

    def token_for(self, request: Request) -> str:
        """Reuse a valid token so several open tabs keep working; otherwise mint one."""
        return self.load(request) or new_token()

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            self.cookie_name,
            self._serializer.dumps(token),
            max_age=LOGIN_CSRF_MAX_AGE_SECONDS,
            path="/",
            secure=self._settings.is_production,
            httponly=True,
            samesite="strict",
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            self.cookie_name,
            path="/",
            secure=self._settings.is_production,
            httponly=True,
            samesite="strict",
        )


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    csrf: str
    token_hash: str
    expires_at: datetime


class AdminSessionManager:
    """Random token in a Strict cookie; PostgreSQL stores only HMAC-SHA256(token)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._key = settings.session_secret.get_secret_value().encode()
        self.cookie_name = cookie_name("fm_admin_session", settings)

    def digest(self, token: str) -> str:
        return hmac.new(self._key, token.encode(), hashlib.sha256).hexdigest()

    def current(self, request: Request, db: Session) -> AdminIdentity | None:
        token = request.cookies.get(self.cookie_name)
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        row = db.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == self.digest(token),
                AdminSession.expires_at > datetime.now(UTC),
            )
        )
        if row is None or row.username != self._settings.admin_username:
            return None
        return AdminIdentity(row.username, row.csrf_token, row.token_hash, row.expires_at)

    def create(self, request: Request, response: Response, db: Session, username: str) -> None:
        """Start a brand new session, discarding any session id the browser presented."""
        old = request.cookies.get(self.cookie_name)
        now = datetime.now(UTC)
        db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
        if old and len(old) <= MAX_TOKEN_LENGTH:
            db.execute(delete(AdminSession).where(AdminSession.token_hash == self.digest(old)))
        token = secrets.token_urlsafe(32)
        db.add(
            AdminSession(
                token_hash=self.digest(token),
                username=username,
                csrf_token=new_token(),
                expires_at=now + timedelta(seconds=self._settings.session_max_age_seconds),
            )
        )
        db.flush()
        response.set_cookie(
            self.cookie_name,
            token,
            max_age=self._settings.session_max_age_seconds,
            path="/",
            secure=self._settings.is_production,
            httponly=True,
            samesite="strict",
        )

    def destroy(self, response: Response, db: Session, identity: AdminIdentity) -> None:
        db.execute(delete(AdminSession).where(AdminSession.token_hash == identity.token_hash))
        response.delete_cookie(
            self.cookie_name,
            path="/",
            secure=self._settings.is_production,
            httponly=True,
            samesite="strict",
        )
