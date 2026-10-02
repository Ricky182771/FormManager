"""GET /api/v1/forms and /api/v1/forms/{slug}: metadata of valid forms only."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.main import create_app
from tests.conftest import admin_login
from tests.forms_fixtures import FORM_A, FORM_B, FORM_C, form_toml, write_package

ClientFactory = Callable[[], TestClient]


@pytest.fixture
def started(engine: Engine, settings_factory: Callable[..., Settings]) -> Iterator[ClientFactory]:
    """Builds a client whose lifespan (catalog load + registry sync) has run."""
    clients: list[TestClient] = []

    def build() -> TestClient:
        client = TestClient(create_app(settings_factory()))
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def test_list_with_zero_forms(started: ClientFactory) -> None:
    res = started().get("/api/v1/forms")
    assert res.status_code == 200
    assert res.json() == {"forms": []}


def test_list_with_one_form(started: ClientFactory, forms_root: Path) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    assert started().get("/api/v1/forms").json() == {
        "forms": [
            {
                "id": FORM_A,
                "slug": "room-booking",
                "title": "Reserva de sala",
                "status": "draft",
                "schema_version": 1,
            }
        ]
    }


def test_list_many_sorted_by_slug_and_stable(started: ClientFactory, forms_root: Path) -> None:
    write_package(forms_root, FORM_A, "zeta")
    write_package(forms_root, FORM_B, "alpha")
    write_package(forms_root, FORM_C, "mid")
    client = started()
    first = client.get("/api/v1/forms").json()
    assert [f["slug"] for f in first["forms"]] == ["alpha", "mid", "zeta"]
    assert started().get("/api/v1/forms").json() == first


def test_invalid_forms_are_excluded(started: ClientFactory, forms_root: Path) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "broken", form="= = =")
    write_package(forms_root, FORM_C, "room-booking-copy", skip=("rules.json",))
    client = started()
    assert [f["id"] for f in client.get("/api/v1/forms").json()["forms"]] == [FORM_A]
    assert client.get("/api/v1/forms/broken").status_code == 404


def test_duplicate_slugs_are_excluded(started: ClientFactory, forms_root: Path) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "room-booking")
    client = started()
    assert client.get("/api/v1/forms").json() == {"forms": []}
    assert client.get("/api/v1/forms/room-booking").status_code == 404


def test_detail_by_slug(started: ClientFactory, forms_root: Path) -> None:
    form = form_toml(
        FORM_A, "room-booking", subtitle="Sala norte", description="Elige **un horario**."
    )
    write_package(forms_root, FORM_A, "room-booking", form=form)
    res = started().get("/api/v1/forms/room-booking")
    assert res.status_code == 200
    assert res.json() == {
        "id": FORM_A,
        "slug": "room-booking",
        "title": "Reserva de sala",
        "status": "draft",
        "schema_version": 1,
        "subtitle": "Sala norte",
        "description": "Elige **un horario**.",  # source text, not rendered
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/forms/missing",
        "/api/v1/forms/" + FORM_A,  # lookup is by slug, not by ID
        "/api/v1/forms/..%2F..%2Fetc%2Fpasswd",
        "/api/v1/forms/Room-Booking",
    ],
)
def test_unknown_form_is_404(started: ClientFactory, forms_root: Path, path: str) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    res = started().get(path)
    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] in {"FORM_NOT_FOUND", "NOT_FOUND"}
    assert str(forms_root) not in res.text


def test_missing_form_has_stable_code(started: ClientFactory) -> None:
    assert started().get("/api/v1/forms/missing").json() == {
        "error": {"code": "FORM_NOT_FOUND", "message": "El formulario no existe."}
    }


def test_no_paths_or_definitions_disclosed(started: ClientFactory, forms_root: Path) -> None:
    package = write_package(forms_root, FORM_A, "room-booking")
    (package / "rules.json").write_text('{"schema_version": 1, "rules": [{"secret": "x"}]}')
    client = started()
    for path in ("/api/v1/forms", "/api/v1/forms/room-booking"):
        text = client.get(path).text
        for leak in (str(forms_root), "/data/forms", "package_path", "relative_path", "rules"):
            assert leak not in text


@pytest.mark.parametrize(
    "path", ["/api/v1/forms/room-booking/definition", "/api/v1/forms/room-booking/elements"]
)
def test_future_endpoints_do_not_exist(started: ClientFactory, forms_root: Path, path: str) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    assert started().get(path).status_code == 404


def test_there_is_no_creation_endpoint(started: ClientFactory) -> None:
    client = started()
    res = client.post("/api/v1/forms", json={"slug": "x", "title": "y"})
    assert res.status_code == 405
    assert res.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert client.get("/api/v1/forms").json() == {"forms": []}


def test_root_and_admin_show_real_count(started: ClientFactory, forms_root: Path) -> None:
    write_package(forms_root, FORM_A, "room-booking")
    write_package(forms_root, FORM_B, "contact")
    write_package(forms_root, FORM_C, "broken", form="= = =")
    client = started()
    count = re.compile(r"Formularios cargados</dt>\s*<dd>2<")
    assert count.search(client.get("/").text)
    assert admin_login(client).status_code == 303
    assert count.search(client.get("/admin").text)
