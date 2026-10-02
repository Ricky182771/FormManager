from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.forms.package import (
    FormDocument,
    is_valid_form_id,
    is_valid_slug,
    new_form_id,
)

BASE: dict[str, Any] = {
    "schema_version": 1,
    "id": "K8mP4qT2xN7rV5sA",
    "slug": "workshop-registration",
    "title": "Inscripción a taller",
    "status": "draft",
}


@pytest.mark.parametrize("value", ["K8mP4qT2xN7rV5sA", "AAAAAAAAAAAAAAAA", "a_b-c_d-0123456z"])
def test_valid_form_id(value: str) -> None:
    assert is_valid_form_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "short",
        "K8mP4qT2xN7rV5sAx",
        "K8mP4qT2xN7rV5s.",
        "../../etc/passwd",
        "K8mP4qT2xN7rV5s/",
        "K8mP4qT2xN7rV5sA\n",
        "",
        16,
        None,
    ],
)
def test_invalid_form_id(value: object) -> None:
    assert not is_valid_form_id(value)


@pytest.mark.parametrize(
    "value", ["contact", "room-booking", "workshop-registration", "a", "x" * 80]
)
def test_valid_slug(value: str) -> None:
    assert is_valid_slug(value)


@pytest.mark.parametrize(
    "value",
    [
        "Room Booking",
        "room_booking",
        "-room",
        "room-",
        "room--booking",
        "../../room",
        "Room",
        "",
        "x" * 81,
        "room\n",
    ],
)
def test_invalid_slug(value: str) -> None:
    assert not is_valid_slug(value)


def test_new_form_id_is_opaque_and_valid() -> None:
    ids = {new_form_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(is_valid_form_id(i) for i in ids)


def test_minimal_document_is_valid() -> None:
    doc = FormDocument.model_validate(BASE)
    assert doc.subtitle is None and doc.description is None


def test_optional_fields_keep_source_text() -> None:
    markdown = "Elige **un horario**.\n\n- uno\n- dos\n<script>x</script>"
    doc = FormDocument.model_validate(BASE | {"subtitle": "Sub", "description": markdown})
    assert doc.description == markdown


@pytest.mark.parametrize("field", ["schema_version", "id", "slug", "title", "status"])
def test_required_fields(field: str) -> None:
    data = {k: v for k, v in BASE.items() if k != field}
    with pytest.raises(ValidationError) as exc:
        FormDocument.model_validate(data)
    assert exc.value.errors()[0]["type"] == "missing"


def test_unknown_property_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        FormDocument.model_validate(BASE | {"banana": "yes"})
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("version", [2, 0, True, 1.0, "1"])
def test_unsupported_schema_version(version: object) -> None:
    with pytest.raises(ValidationError):
        FormDocument.model_validate(BASE | {"schema_version": version})


@pytest.mark.parametrize("status", ["draft", "open", "paused", "closed", "archived"])
def test_valid_statuses(status: str) -> None:
    assert FormDocument.model_validate(BASE | {"status": status}).status == status


@pytest.mark.parametrize("status", ["OPEN", "published", "", 1])
def test_invalid_status(status: object) -> None:
    with pytest.raises(ValidationError):
        FormDocument.model_validate(BASE | {"status": status})


@pytest.mark.parametrize(
    "patch",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "bad\x00title"},
        {"title": "line\nbreak"},
        {"title": 5},
        {"subtitle": "nul\x00"},
        {"subtitle": "x" * 301},
        {"description": "bell\x07"},
        {"description": "x" * 20_001},
    ],
)
def test_text_fields_reject_bad_values(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FormDocument.model_validate(BASE | patch)
