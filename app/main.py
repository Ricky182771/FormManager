from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.db.session import build_engine, build_session_factory, ping
from app.logging_setup import configure_logging
from app.middleware import (
    BodySizeLimitMiddleware,
    RequestLogMiddleware,
    SecurityHeadersMiddleware,
    error_body,
)
from app.routes import admin, health, public
from app.security.rate_limit import SlidingWindowRateLimiter
from app.security.sessions import AdminSessionManager, LoginCsrfCodec
from app.storage import prepare_forms_dir
from app.web import STATIC_DIR, Services, build_templates, render, wants_json

logger = logging.getLogger("app")

ERRORS: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Petición inválida"),
    401: ("UNAUTHENTICATED", "No autenticado"),
    403: ("FORBIDDEN", "Acceso denegado"),
    404: ("NOT_FOUND", "Página no encontrada"),
    405: ("METHOD_NOT_ALLOWED", "Método no permitido"),
    409: ("CONFLICT", "Conflicto"),
    413: ("PAYLOAD_TOO_LARGE", "Petición demasiado grande"),
    422: ("VALIDATION_ERROR", "Datos inválidos"),
    429: ("RATE_LIMITED", "Demasiados intentos"),
    500: ("INTERNAL_ERROR", "Error interno"),
    503: ("SERVICE_UNAVAILABLE", "Servicio no disponible"),
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Fails startup if FORMS_DIR is unusable; its contents are never read in Hito 0.
    forms_dir = prepare_forms_dir(settings.forms_dir)
    engine = build_engine(settings)
    svc = Services(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        limiter=SlidingWindowRateLimiter(),
        login_csrf=LoginCsrfCodec(settings),
        admin_sessions=AdminSessionManager(settings),
        templates=build_templates(settings.tz),
        forms_dir=forms_dir,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup",
            extra={
                "env": settings.app_env,
                "admin_enabled": settings.admin_enabled,
                "db_reachable": ping(engine),
            },
        )
        yield
        engine.dispose()
        logger.info("shutdown")

    app = FastAPI(
        title="FormManager",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = svc

    # Added innermost first: the security headers wrap everything, including 413 responses.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(admin.router)

    _register_error_handlers(app)
    return app


def _error_response(request: Request, status: int, message: str) -> Response:
    code, title = ERRORS.get(status, ("ERROR", "Error"))
    if wants_json(request):
        return JSONResponse(error_body(code, message), status_code=status)
    return render(
        request, "error.html", {"status": status, "title": title, "detail": message}, status
    )


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(admin.AdminRedirect)
    async def _admin_redirect(request: Request, exc: admin.AdminRedirect) -> Response:
        return RedirectResponse("/admin/login", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        default = ERRORS.get(exc.status_code, ("ERROR", "Error"))[1] + "."
        detail = exc.detail if isinstance(exc.detail, str) else default
        if exc.status_code == 404:
            detail = "El recurso solicitado no existe."
        elif exc.status_code == 405:
            detail = "Método no permitido."
        response = _error_response(request, exc.status_code, detail)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        # Never echo the submitted input back; only the field names.
        fields = sorted(
            {".".join(str(p) for p in err.get("loc", ()) if p != "body") for err in exc.errors()}
        )
        message = "Los datos enviados no son válidos."
        if wants_json(request):
            return JSONResponse(
                {"error": {"code": "VALIDATION_ERROR", "message": message, "fields": fields}},
                status_code=422,
            )
        return _error_response(request, 422, message)

    @app.exception_handler(OperationalError)
    async def _db_down(request: Request, exc: OperationalError) -> Response:
        logger.error("database_error", extra={"error_type": type(exc.orig).__name__})
        return _error_response(
            request, 503, "La base de datos no está disponible. Intenta de nuevo en unos segundos."
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return _error_response(request, 500, "Ocurrió un error inesperado.")
