from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from app.forms import creator, fsutil
from app.forms.creator import FormCreationError, create_form_package
from app.forms.diagnostics import Diagnostic, DiagnosticCode
from app.forms.elements import ElementsSchema
from app.forms.loader import PackageResult, scan_forms_dir
from app.forms.package import is_valid_form_id
from tests.forms_fixtures import FORM_A, write_package

MAX = 64 * 1024


def leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".tmp-"))


def test_creates_a_package_the_loader_accepts(tmp_path: Path) -> None:
    package = create_form_package(
        tmp_path,
        slug="room-booking",
        title='Reserva de sala "A" \\ norte',
        subtitle="Formulario de prueba",
        description="Elige **un horario**.\n\n- mañana\n- tarde",
        max_bytes=MAX,
    )
    assert is_valid_form_id(package.id)
    assert package.package_path == tmp_path / package.id
    [loaded] = scan_forms_dir(tmp_path, MAX).forms
    assert loaded == package
    assert loaded.description == "Elige **un horario**.\n\n- mañana\n- tarde"
    # The skeleton declares no elements, which is a valid (draft) schema since Hito 2.
    assert loaded.elements == ElementsSchema()
    assert leftovers(tmp_path) == []


def test_generated_ids_are_opaque_and_distinct(tmp_path: Path) -> None:
    ids = {
        create_form_package(tmp_path, slug=f"form-{i}", title="Contacto", max_bytes=MAX).id
        for i in range(5)
    }
    assert len(ids) == 5 and all(is_valid_form_id(i) for i in ids)


def test_skeleton_files(tmp_path: Path) -> None:
    package = create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    root = package.package_path
    assert sorted(p.name for p in root.iterdir()) == [
        "elements.toml",
        "form.toml",
        "resources.toml",
        "rules.json",
    ]
    form = tomllib.loads((root / "form.toml").read_text())
    assert form == {
        "schema_version": 1,
        "id": package.id,
        "slug": "contact",
        "title": "Contacto",
        "status": "draft",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slug": "../../room", "title": "Reserva de sala"},
        {"slug": "Room Booking", "title": "Reserva de sala"},
        {"slug": "room-booking", "title": ""},
        {"slug": "room-booking", "title": "x\x00"},
        {"slug": "room-booking", "title": "ok", "status": "published"},
    ],
)
def test_rejects_invalid_input_without_touching_disk(
    tmp_path: Path, kwargs: dict[str, str]
) -> None:
    with pytest.raises(FormCreationError) as exc:
        create_form_package(tmp_path, max_bytes=MAX, **kwargs)  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_INPUT"
    assert list(tmp_path.iterdir()) == []


def test_rejects_slug_already_in_use(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    with pytest.raises(FormCreationError) as exc:
        create_form_package(tmp_path, slug="room-booking", title="Otra", max_bytes=MAX)
    assert exc.value.code == "SLUG_TAKEN"
    assert [f.id for f in scan_forms_dir(tmp_path, MAX).forms] == [FORM_A]


def test_never_overwrites_an_existing_package(tmp_path: Path) -> None:
    existing = write_package(tmp_path, FORM_A, "contact")
    before = {p.name: p.read_bytes() for p in existing.iterdir()}
    with pytest.raises(FormCreationError) as exc:
        create_form_package(
            tmp_path, slug="room-booking", title="Reserva", max_bytes=MAX, id_factory=lambda: FORM_A
        )
    assert exc.value.code == "FORM_EXISTS"
    assert {p.name: p.read_bytes() for p in existing.iterdir()} == before
    assert leftovers(tmp_path) == []


def test_never_overwrites_a_package_that_appears_mid_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = creator.load_package

    def load_then_race(*args: object, **kwargs: object) -> PackageResult:
        result = real_load(*args, **kwargs)  # type: ignore[arg-type]
        write_package(tmp_path, FORM_A, "contact")
        return result

    monkeypatch.setattr(creator, "load_package", load_then_race)
    with pytest.raises(FormCreationError):
        create_form_package(
            tmp_path, slug="room-booking", title="Reserva", max_bytes=MAX, id_factory=lambda: FORM_A
        )
    assert [f.slug for f in scan_forms_dir(tmp_path, MAX).forms] == ["contact"]
    assert leftovers(tmp_path) == []


def test_stages_under_tmp_then_renames_the_validated_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, object]] = []
    real_move = fsutil.move_dir

    def spy(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
        [staging] = leftovers(tmp_path)
        seen.append(
            {
                "staging": staging,
                "src": src,
                "dst": dst,
                "staged_files": sorted(os.listdir(tmp_path / staging / src)),
                "final_existed": (tmp_path / dst).exists(),
            }
        )
        real_move(src_fd, src, dst_fd, dst)

    monkeypatch.setattr(fsutil, "move_dir", spy)
    package = create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    [call] = seen
    assert str(call["staging"]).startswith(".tmp-")
    assert call["src"] == call["dst"] == package.id
    assert call["staged_files"] == ["elements.toml", "form.toml", "resources.toml", "rules.json"]
    assert call["final_existed"] is False
    assert leftovers(tmp_path) == []  # empty staging container removed


def test_staged_package_is_validated_by_the_normal_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_load = creator.load_package

    def spy(parent_fd: int, name: str, **kwargs: object) -> PackageResult:
        calls.append(name)
        return real_load(parent_fd, name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(creator, "load_package", spy)
    package = create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    assert calls == [package.id]  # the real ID: directory name and form.toml must agree


def test_cleans_up_when_rename_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(fsutil, "move_dir", boom)
    with pytest.raises(OSError):
        create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    assert list(tmp_path.iterdir()) == []


def test_cleans_up_when_validation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*_: object, **__: object) -> PackageResult:
        diag = Diagnostic("x", "form.toml", DiagnosticCode.INVALID_TOML, "TOML inválido.")
        return PackageResult(None, (diag,))

    monkeypatch.setattr(creator, "load_package", reject)
    with pytest.raises(FormCreationError) as exc:
        create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    assert exc.value.code == "INVALID_PACKAGE"
    assert list(tmp_path.iterdir()) == []


def test_cleans_up_when_writing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_write(*_: object) -> None:
        raise OSError("io error")

    monkeypatch.setattr(fsutil, "write_new_file", broken_write)
    with pytest.raises(OSError):
        create_form_package(tmp_path, slug="contact", title="Contacto", max_bytes=MAX)
    assert list(tmp_path.iterdir()) == []
