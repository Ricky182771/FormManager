from __future__ import annotations

import io
import json
import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.forms.catalog import FormCatalog
from app.forms.package import FormPackage
from app.logging_setup import JsonFormatter
from tests.forms_fixtures import FORM_A, FORM_B, FORM_C, write_package

MAX = 64 * 1024


class RecordingSync:
    def __init__(self) -> None:
        self.calls: list[tuple[FormPackage, ...]] = []
        self.fail = False

    def __call__(self, forms: tuple[FormPackage, ...]) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(forms)


@pytest.fixture
def sync() -> RecordingSync:
    return RecordingSync()


@pytest.fixture
def catalog(tmp_path: Path, sync: RecordingSync) -> FormCatalog:
    return FormCatalog(tmp_path, MAX, sync)


def test_starts_empty_until_reload(catalog: FormCatalog, tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    assert catalog.count == 0
    catalog.reload()
    assert catalog.count == 1


def test_lookup_by_id_and_slug(catalog: FormCatalog, tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    write_package(tmp_path, FORM_B, "contact")
    catalog.reload()
    assert [f.slug for f in catalog.forms()] == ["contact", "room-booking"]
    found = catalog.get_by_slug("room-booking")
    assert found is not None and found.id == FORM_A
    assert catalog.get_by_id(FORM_B) is catalog.get_by_slug("contact")
    assert catalog.get_by_slug("../" + FORM_A) is None
    assert catalog.get_by_id("missing") is None


def test_reload_syncs_exactly_the_valid_forms(
    catalog: FormCatalog, sync: RecordingSync, tmp_path: Path
) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    write_package(tmp_path, FORM_B, "broken", skip=("rules.json",))
    snapshot = catalog.reload()
    assert [f.id for f in sync.calls[-1]] == [FORM_A]
    assert snapshot.invalid_packages == 1
    assert {d.relative_path for d in catalog.diagnostics} == {FORM_B}


def test_reload_picks_up_changes(catalog: FormCatalog, tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    catalog.reload()
    shutil.rmtree(tmp_path / FORM_A)
    write_package(tmp_path, FORM_C, "contact")
    catalog.reload()
    assert [f.id for f in catalog.forms()] == [FORM_C]


def test_sync_failure_keeps_previous_snapshot(
    catalog: FormCatalog, sync: RecordingSync, tmp_path: Path
) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    first = catalog.reload()
    write_package(tmp_path, FORM_B, "contact")
    sync.fail = True
    with pytest.raises(RuntimeError):
        catalog.reload()
    assert catalog.snapshot is first
    assert catalog.count == 1


def test_snapshot_is_immutable(catalog: FormCatalog, tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    snapshot = catalog.reload()
    with pytest.raises(TypeError):
        snapshot.by_slug["x"] = snapshot.forms[0]  # type: ignore[index]
    with pytest.raises(AttributeError):
        snapshot.forms[0].slug = "changed"  # type: ignore[misc]


def test_reload_is_deterministic(catalog: FormCatalog, tmp_path: Path) -> None:
    for form_id, slug in ((FORM_C, "c"), (FORM_A, "a"), (FORM_B, "b")):
        write_package(tmp_path, form_id, slug)
    assert catalog.reload().forms == catalog.reload().forms


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_load_events_are_structured_and_safe(
    catalog: FormCatalog, tmp_path: Path, captured_logs: io.StringIO
) -> None:
    write_package(tmp_path, FORM_A, "room-booking", title="ALICE EXAMPLE secret title")
    package = write_package(tmp_path, FORM_B, "broken")
    (package / "rules.json").write_text('{"schema_version": 1, "token": "BOB EXAMPLE"')
    catalog.reload()
    events = [json.loads(line) for line in captured_logs.getvalue().splitlines()]
    by_event = {e["event"]: e for e in events}
    assert {"form_load_started", "form_loaded", "form_load_failed", "form_catalog_loaded"} <= set(
        by_event
    )
    assert by_event["form_loaded"]["form_id"] == FORM_A
    assert by_event["form_loaded"]["slug"] == "room-booking"
    failed = by_event["form_load_failed"]
    assert (failed["relative_path"], failed["file"], failed["error_code"]) == (
        FORM_B,
        "rules.json",
        "INVALID_JSON",
    )
    output = captured_logs.getvalue()
    for leak in (str(tmp_path), "ALICE EXAMPLE", "BOB EXAMPLE", "Traceback"):
        assert leak not in output
