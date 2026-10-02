from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.db.session import ping
from app.web import render, services

router = APIRouter()


@router.get("/", response_class=Response)
def index(request: Request) -> Response:
    return render(
        request,
        "index.html",
        {"db_ok": ping(services(request).engine), "forms_loaded": services(request).catalog.count},
    )
