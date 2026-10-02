"""Public API v1. Hito 1 exposes form metadata only: no definition content, no paths."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.forms.package import FormPackage
from app.middleware import error_body
from app.web import services

router = APIRouter(prefix="/api/v1")


def _summary(form: FormPackage) -> dict[str, Any]:
    return {
        "id": form.id,
        "slug": form.slug,
        "title": form.title,
        "status": form.status,
        "schema_version": form.schema_version,
    }


@router.get("/forms")
def list_forms(request: Request) -> JSONResponse:
    """Valid forms only, ordered by slug (unique and stable across reloads)."""
    return JSONResponse({"forms": [_summary(f) for f in services(request).catalog.forms()]})


@router.get("/forms/{slug}")
def get_form(request: Request, slug: str) -> JSONResponse:
    form = services(request).catalog.get_by_slug(slug)
    if form is None:
        return JSONResponse(
            error_body("FORM_NOT_FOUND", "El formulario no existe."), status_code=404
        )
    # Raw source text: Markdown is not rendered until its own milestone.
    detail = _summary(form) | {"subtitle": form.subtitle, "description": form.description}
    return JSONResponse(detail)
