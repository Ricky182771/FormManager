from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db.session import ping
from app.security.csrf import same_origin, tokens_match
from app.security.passwords import verify_secret
from app.security.rate_limit import client_ip
from app.security.sessions import AdminIdentity
from app.services.audit import AuditAction, record_audit
from app.storage import FORMS_LOADED
from app.web import get_db, render, services

router = APIRouter(prefix="/admin")
logger = logging.getLogger("app.admin")

MSG_BAD_LOGIN = "Usuario o contraseña incorrectos."
MSG_FORM_EXPIRED = "El formulario expiró. Recarga la página e inténtalo de nuevo."


class AdminRedirect(Exception):
    """Unauthenticated GET on an admin page: send the browser to the login form."""


def current_admin(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> AdminIdentity | None:
    return services(request).admin_sessions.current(request, db)


def require_admin_page(
    identity: Annotated[AdminIdentity | None, Depends(current_admin)],
) -> AdminIdentity:
    if identity is None:
        raise AdminRedirect
    return identity


# Empty-string defaults are form fields, not credentials (bandit B107 false positive).
def require_admin_action(  # nosec B107
    request: Request,
    identity: Annotated[AdminIdentity | None, Depends(current_admin)],
    csrf_token: Annotated[str, Form(max_length=200)] = "",
) -> AdminIdentity:
    if identity is None:
        raise HTTPException(status_code=401, detail="Inicia sesión como administrador.")
    if not same_origin(request) or not tokens_match(identity.csrf, csrf_token):
        logger.warning("admin_csrf_rejected")
        raise HTTPException(status_code=403, detail="Token CSRF inválido. Recarga la página.")
    return identity


PageAdmin = Annotated[AdminIdentity, Depends(require_admin_page)]
ActionAdmin = Annotated[AdminIdentity, Depends(require_admin_action)]
Db = Annotated[Session, Depends(get_db)]


@router.get("/login", response_class=Response)
def login_form(
    request: Request, identity: Annotated[AdminIdentity | None, Depends(current_admin)]
) -> Response:
    if identity is not None:
        return RedirectResponse("/admin", status_code=303)
    return _render_login(request)


def _render_login(
    request: Request, status_code: int = 200, error: str | None = None, username: str = ""
) -> Response:
    svc = services(request)
    token = svc.login_csrf.token_for(request)
    response = render(
        request,
        "admin/login.html",
        {
            "admin_enabled": svc.settings.admin_enabled,
            "csrf": token,
            "error": error,
            "username": username[:80],
        },
        status_code,
    )
    svc.login_csrf.set_cookie(response, token)
    return response


@router.post("/login", response_class=Response)
# Empty-string defaults are form fields, not credentials (bandit B107 false positive).
def login_submit(  # nosec B107
    request: Request,
    db: Db,
    username: Annotated[str, Form(max_length=200)] = "",
    password: Annotated[str, Form(max_length=1024)] = "",
    csrf_token: Annotated[str, Form(max_length=200)] = "",
) -> Response:
    svc = services(request)
    settings = svc.settings
    if not same_origin(request) or not tokens_match(svc.login_csrf.load(request), csrf_token):
        return _render_login(request, 403, MSG_FORM_EXPIRED, username)
    decision = svc.limiter.hit("admin_login", client_ip(request), settings.admin_login_limit)
    if not decision.allowed:
        response = _render_login(
            request, 429, f"Demasiados intentos. Espera {decision.retry_after} segundos.", username
        )
        response.headers["Retry-After"] = str(decision.retry_after)
        return response
    if not settings.admin_enabled:
        return _render_login(request, 503, "La administración no está configurada.", username)

    user_ok = hmac.compare_digest(username.encode(), settings.admin_username.encode())
    stored = (
        settings.admin_password_hash.get_secret_value() if settings.admin_password_hash else None
    )
    # Always run Argon2 so a wrong username costs as much as a wrong password.
    password_ok = verify_secret(stored if user_ok else None, password)
    if not (user_ok and password_ok):
        record_audit(db, AuditAction.ADMIN_LOGIN_FAILED)
        db.commit()
        return _render_login(request, 401, MSG_BAD_LOGIN, username)

    redirect = RedirectResponse("/admin", status_code=303)
    svc.admin_sessions.create(request, redirect, db, settings.admin_username)
    svc.login_csrf.clear(redirect)
    record_audit(db, AuditAction.ADMIN_LOGIN, admin=settings.admin_username)
    db.commit()
    return redirect


@router.post("/logout", response_class=Response)
def logout(request: Request, db: Db, identity: ActionAdmin) -> Response:
    response = RedirectResponse("/admin/login", status_code=303)
    services(request).admin_sessions.destroy(response, db, identity)
    record_audit(db, AuditAction.ADMIN_LOGOUT, admin=identity.username)
    db.commit()
    return response


@router.get("", response_class=Response)
def dashboard(request: Request, identity: PageAdmin) -> Response:
    return render(
        request,
        "admin/dashboard.html",
        {
            "admin": identity,
            "csrf": identity.csrf,
            "db_ok": ping(services(request).engine),
            "forms_loaded": FORMS_LOADED,
        },
    )
