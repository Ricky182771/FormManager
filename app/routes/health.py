from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db.session import ping
from app.web import services

router = APIRouter()
logger = logging.getLogger("app.health")


@router.get("/health", include_in_schema=False)
def health(request: Request) -> JSONResponse:
    if ping(services(request).engine):
        return JSONResponse({"status": "ok", "database": "ok"})
    logger.error("health_db_unreachable")
    return JSONResponse({"status": "unavailable", "database": "unavailable"}, status_code=503)
