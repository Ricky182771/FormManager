"""Filesystem and parser hardening of the Form Loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.forms.diagnostics import DiagnosticCode
from app.forms.loader import scan_forms_dir
from tests.forms_fixtures import FORM_A, FORM_B, form_toml, write_package

MAX = 64 * 1024


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    target = tmp_path / "outside"
    target.mkdir()
    write_package(target, FORM_B, "escaped")
    (target / "secret.toml").write_text('schema_version = 1\nsecret = "ALICE EXAMPLE"\n')
    return target


@pytest.fixture
def root(tmp_path: Path) -> Path:
    forms = tmp_path / "forms"
    forms.mkdir()
    return forms


def test_symlinked_package_directory_is_rejected(root: Path, outside: Path) -> None:
    (root / FORM_B).symlink_to(outside / FORM_B, target_is_directory=True)
    result = scan_forms_dir(root, MAX)
    assert result.forms == ()
    assert [(d.relative_path, d.code) for d in result.diagnostics] == [
        (FORM_B, DiagnosticCode.SYMLINK_NOT_ALLOWED)
    ]


@pytest.mark.parametrize("name", ["form.toml", "elements.toml", "resources.toml", "rules.json"])
def test_symlinked_required_file_is_rejected(root: Path, outside: Path, name: str) -> None:
    package = write_package(root, FORM_A, "room-booking", skip=(name,))
    (package / name).symlink_to(outside / FORM_B / name)
    result = scan_forms_dir(root, MAX)
    assert result.forms == ()
    assert [(d.code, d.file) for d in result.diagnostics] == [
        (DiagnosticCode.SYMLINK_NOT_ALLOWED, name)
    ]


def test_symlink_inside_package_to_sibling_file_is_rejected(root: Path) -> None:
    package = write_package(root, FORM_A, "room-booking", skip=("resources.toml",))
    (package / "resources.toml").symlink_to(package / "elements.toml")
    assert {d.code for d in scan_forms_dir(root, MAX).diagnostics} == {
        DiagnosticCode.SYMLINK_NOT_ALLOWED
    }


@pytest.mark.parametrize("name", ["resources", "assets", "ui"])
def test_symlinked_optional_directory_is_rejected(root: Path, outside: Path, name: str) -> None:
    package = write_package(root, FORM_A, "room-booking")
    (package / name).symlink_to(outside, target_is_directory=True)
    result = scan_forms_dir(root, MAX)
    assert result.forms == ()
    assert [(d.code, d.file) for d in result.diagnostics] == [
        (DiagnosticCode.SYMLINK_NOT_ALLOWED, name)
    ]


@pytest.mark.parametrize("name", ["resources", "assets", "ui"])
def test_optional_entry_must_be_a_directory(root: Path, name: str) -> None:
    package = write_package(root, FORM_A, "room-booking")
    (package / name).write_text("not a dir")
    assert [d.code for d in scan_forms_dir(root, MAX).diagnostics] == [
        DiagnosticCode.NOT_A_DIRECTORY
    ]


def test_traversal_ids_never_resolve_outside(root: Path, outside: Path) -> None:
    # A package whose id tries to point elsewhere fails validation instead of being followed.
    write_package(root, FORM_A, "room-booking", form=form_toml("../outside/BBBB", "room-booking"))
    result = scan_forms_dir(root, MAX)
    assert result.forms == ()
    assert {d.code for d in result.diagnostics} == {DiagnosticCode.INVALID_FORM_ID}


def test_forms_dir_itself_as_symlink_is_refused(tmp_path: Path, root: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        scan_forms_dir(link, MAX)


def test_nested_packages_are_not_discovered(root: Path) -> None:
    outer = write_package(root, FORM_A, "room-booking")
    (outer / "ui").mkdir()
    write_package(outer / "ui", FORM_B, "nested")
    assert [f.id for f in scan_forms_dir(root, MAX).forms] == [FORM_A]


def test_huge_file_is_rejected_without_reading_it_all(root: Path) -> None:
    package = write_package(root, FORM_A, "room-booking", skip=("elements.toml",))
    with (package / "elements.toml").open("wb") as fh:
        fh.truncate(512 * 1024 * 1024)  # sparse: 512 MiB declared, no disk used
    result = scan_forms_dir(root, MAX)
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.FILE_TOO_LARGE]


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("elements.toml", "a = " + "[" * 5000 + "]" * 5000, DiagnosticCode.INVALID_TOML),
        ("rules.json", "[" * 50_000 + "]" * 50_000, DiagnosticCode.INVALID_JSON),
        ("form.toml", "\x00\x01\x02", DiagnosticCode.INVALID_TOML),
        ("rules.json", "﻿{}", DiagnosticCode.INVALID_JSON),
    ],
)
def test_hostile_parser_input_fails_cleanly(
    root: Path, name: str, content: str, code: DiagnosticCode
) -> None:
    package = write_package(root, FORM_A, "room-booking")
    (package / name).write_text(content, encoding="utf-8")
    result = scan_forms_dir(root, 1024 * 1024)
    assert code in {d.code for d in result.diagnostics}


def test_nul_in_title_is_rejected_before_reaching_the_registry(root: Path) -> None:
    write_package(root, FORM_A, "room-booking", form=form_toml(FORM_A, "room-booking", "a\x00b"))
    assert {d.code for d in scan_forms_dir(root, MAX).diagnostics} == {
        DiagnosticCode.INVALID_PROPERTY
    }


def test_diagnostics_never_contain_absolute_paths_or_tracebacks(root: Path, outside: Path) -> None:
    write_package(root, FORM_A, "broken", form="= = =")
    (root / FORM_B).symlink_to(outside / FORM_B, target_is_directory=True)
    (root / "weird\nname").mkdir()
    write_package(root, "CCCCCCCCCCCCCCCC", "x", skip=("rules.json",))
    result = scan_forms_dir(root, MAX)
    assert len(result.diagnostics) >= 4
    for diag in result.diagnostics:
        text = f"{diag.relative_path} {diag.file} {diag.message}"
        assert str(root) not in text and str(outside) not in text
        assert "Traceback" not in text and "\n" not in text
