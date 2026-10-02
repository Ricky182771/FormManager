"""Shared request plumbing: services container, DB session dependency, templates."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import HTMLResponse

from app.config import Settings
from app.security.rate_limit import SlidingWindowRateLimiter
from app.security.sessions import AdminSessionManager, LoginCsrfCodec

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class Services:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    limiter: SlidingWindowRateLimiter
    login_csrf: LoginCsrfCodec
    admin_sessions: AdminSessionManager
    templates: Environment
    forms_dir: Path


def build_templates(tz: ZoneInfo) -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"], default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def localtime(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
        if value is None:
            return ""
        return value.astimezone(tz).strftime(fmt)

    env.filters["localtime"] = localtime
    return env


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


def get_db(request: Request) -> Iterator[Session]:
    session = services(request).session_factory()
    try:
        yield session
    finally:
        session.close()


def render(
    request: Request, template: str, context: dict[str, Any] | None = None, status_code: int = 200
) -> HTMLResponse:
    svc = services(request)
    ctx: dict[str, Any] = {"request": request, "timezone": svc.settings.app_timezone}
    ctx.update(context or {})
    html = svc.templates.get_template(template).render(ctx)
    return HTMLResponse(html, status_code=status_code)


def wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or request.url.path == "/health"
