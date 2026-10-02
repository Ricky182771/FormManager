from __future__ import annotations

import json
import os
import socket
import tomllib
from pathlib import Path

import pytest

from app.forms.diagnostics import DiagnosticCode
from app.forms.loader import ScanResult, resolve_conflicts, scan_forms_dir
from app.forms.package import FormPackage
from tests.forms_fixtures import FORM_A, FORM_B, FORM_C, form_toml, write_package

MAX = 4096


def scan(root: Path) -> ScanResult:
    return scan_forms_dir(root, MAX)


def codes(result: ScanResult) -> set[DiagnosticCode]:
    return {d.code for d in result.diagnostics}


def only_codes_for(result: ScanResult, rel: str) -> set[DiagnosticCode]:
    return {d.code for d in result.diagnostics if d.relative_path == rel}


def test_empty_forms_dir(tmp_path: Path) -> None:
    result = scan(tmp_path)
    assert result.forms == () and result.diagnostics == ()


def test_one_valid_package(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    result = scan(tmp_path)
    assert result.diagnostics == ()
    [form] = result.forms
    assert (form.id, form.slug, form.title, form.status) == (
        FORM_A,
        "room-booking",
        "Reserva de sala",
        "draft",
    )
    assert form.relative_path == FORM_A
    assert form.package_path == tmp_path / FORM_A


def test_multiple_packages_sorted_by_slug(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "zeta")
    write_package(tmp_path, FORM_B, "alpha")
    write_package(tmp_path, FORM_C, "mid")
    assert [f.slug for f in scan(tmp_path).forms] == ["alpha", "mid", "zeta"]


def test_order_does_not_depend_on_creation_order(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    for root, order in ((first, (FORM_A, FORM_B, FORM_C)), (second, (FORM_C, FORM_B, FORM_A))):
        for form_id in order:
            write_package(root, form_id, form_id.lower())
    assert [f.id for f in scan(first).forms] == [f.id for f in scan(second).forms]


def test_optional_directories_are_accepted_and_not_read(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    for name in ("resources", "assets", "ui"):
        (package / name).mkdir()
    (package / "assets" / "huge.bin").write_bytes(b"\0" * (MAX * 4))
    (package / "resources" / "broken.json").write_text("{not json")
    assert len(scan(tmp_path).forms) == 1


def test_tmp_and_dot_directories_are_ignored(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    (tmp_path / ".tmp-AAAAAAAAAAAAAAAA-0001").mkdir()
    (tmp_path / ".hidden").mkdir()
    result = scan(tmp_path)
    assert len(result.forms) == 1 and result.diagnostics == ()


def test_loose_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "README.txt").write_text("not a form")
    (tmp_path / FORM_B).write_text("a file named like an id")
    result = scan(tmp_path)
    assert result.forms == () and result.diagnostics == ()


def test_invalid_directory_name(tmp_path: Path) -> None:
    for name in ("short", "room booking 16c", "K8mP4qT2xN7rV5sA0"):
        (tmp_path / name).mkdir()
    result = scan(tmp_path)
    assert result.forms == ()
    assert [d.code for d in result.diagnostics] == [DiagnosticCode.INVALID_DIRECTORY_NAME] * 3


def test_directory_id_mismatch(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking", form=form_toml(FORM_B, "room-booking"))
    result = scan(tmp_path)
    assert result.forms == ()
    assert codes(result) == {DiagnosticCode.FORM_ID_MISMATCH}


@pytest.mark.parametrize("missing", ["form.toml", "elements.toml", "resources.toml", "rules.json"])
def test_missing_required_file(tmp_path: Path, missing: str) -> None:
    write_package(tmp_path, FORM_A, "room-booking", skip=(missing,))
    result = scan(tmp_path)
    assert result.forms == ()
    [diag] = result.diagnostics
    assert (diag.code, diag.file) == (DiagnosticCode.MISSING_FILE, missing)


def test_required_file_is_directory(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking", skip=("rules.json",))
    (package / "rules.json").mkdir()
    result = scan(tmp_path)
    assert [(d.code, d.file) for d in result.diagnostics] == [
        (DiagnosticCode.NOT_A_REGULAR_FILE, "rules.json")
    ]


def test_required_file_is_fifo_or_socket(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking", skip=("rules.json", "elements.toml"))
    os.mkfifo(package / "rules.json")
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(package / "elements.toml"))
        result = scan(tmp_path)  # must not block on the FIFO
    finally:
        sock.close()
    assert {(d.code, d.file) for d in result.diagnostics} == {
        (DiagnosticCode.NOT_A_REGULAR_FILE, "rules.json"),
        (DiagnosticCode.NOT_A_REGULAR_FILE, "elements.toml"),
    }


def test_malformed_toml(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking", form='schema_version = 1\nid = "unterminated\n')
    result = scan(tmp_path)
    assert codes(result) == {DiagnosticCode.INVALID_TOML}


def test_malformed_json(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "rules.json").write_text('{"schema_version": 1, "rules": [}')
    assert codes(scan(tmp_path)) == {DiagnosticCode.INVALID_JSON}


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version": 1, "schema_version": 1}',
        '{"schema_version": 1, "rules": [NaN]}',
        '{"schema_version": 1, "x": Infinity}',
    ],
)
def test_json_duplicates_and_non_finite_numbers_are_rejected(tmp_path: Path, content: str) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "rules.json").write_text(content)
    assert codes(scan(tmp_path)) == {DiagnosticCode.INVALID_JSON}


@pytest.mark.parametrize("content", ["[]", '"x"', "1", "null"])
def test_json_root_must_be_object(tmp_path: Path, content: str) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "rules.json").write_text(content)
    assert codes(scan(tmp_path)) == {DiagnosticCode.INVALID_JSON_ROOT}


@pytest.mark.parametrize("name", ["elements.toml", "resources.toml"])
@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("", DiagnosticCode.MISSING_PROPERTY),
        ("schema_version = 2\n", DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION),
        ("schema_version = true\n", DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION),
        ('schema_version = "1"\n', DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION),
    ],
)
def test_toml_schema_version(tmp_path: Path, name: str, content: str, code: DiagnosticCode) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / name).write_text(content)
    result = scan(tmp_path)
    assert [(d.code, d.file) for d in result.diagnostics] == [(code, name)]


@pytest.mark.parametrize("version", ["1.0", "2", '"1"', "true"])
def test_rules_schema_version(tmp_path: Path, version: str) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "rules.json").write_text(f'{{"schema_version": {version}}}')
    assert codes(scan(tmp_path)) == {DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION}


def test_future_keys_in_deferred_files_are_not_interpreted(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "elements.toml").write_text(
        'schema_version = 1\n[[element]]\nid = "email"\ntype = "anything-for-now"\n'
    )
    (package / "rules.json").write_text(
        json.dumps({"schema_version": 1, "rules": [{"type": "not-yet-defined"}]})
    )
    assert len(scan(tmp_path).forms) == 1


def test_form_toml_diagnostic_codes(tmp_path: Path) -> None:
    form = (
        "schema_version = 3\n"
        'id = "bad id"\n'
        'slug = "Bad_Slug"\n'
        'title = "Reserva de sala"\n'
        'status = "published"\n'
        'banana = "yes"\n'
        "[access]\n"
        'mode = "code"\n'
    )
    write_package(tmp_path, FORM_A, "room-booking", form=form)
    assert codes(scan(tmp_path)) == {
        DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION,
        DiagnosticCode.INVALID_FORM_ID,
        DiagnosticCode.INVALID_SLUG,
        DiagnosticCode.INVALID_STATUS,
        DiagnosticCode.UNKNOWN_FORM_PROPERTY,
    }


def test_unknown_property_message_names_it(tmp_path: Path) -> None:
    write_package(
        tmp_path, FORM_A, "room-booking", form=form_toml(FORM_A, "room-booking", banana="yes")
    )
    [diag] = scan(tmp_path).diagnostics
    assert diag.code is DiagnosticCode.UNKNOWN_FORM_PROPERTY and "banana" in diag.message


def test_missing_form_property(tmp_path: Path) -> None:
    form = f'schema_version = 1\nid = "{FORM_A}"\nslug = "room-booking"\nstatus = "draft"\n'
    write_package(tmp_path, FORM_A, "room-booking", form=form)
    [diag] = scan(tmp_path).diagnostics
    assert diag.code is DiagnosticCode.MISSING_PROPERTY and "title" in diag.message


def test_invalid_utf8(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "elements.toml").write_bytes(b"schema_version = 1\n# \xff\xfe\n")
    assert codes(scan(tmp_path)) == {DiagnosticCode.INVALID_ENCODING}


def test_oversized_definition_file(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "elements.toml").write_text("schema_version = 1\n" + "# pad\n" * MAX)
    result = scan(tmp_path)
    assert [(d.code, d.file) for d in result.diagnostics] == [
        (DiagnosticCode.FILE_TOO_LARGE, "elements.toml")
    ]


def test_size_limit_applies_before_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    (package / "form.toml").write_text("x" * (MAX + 1))

    real_loads = tomllib.loads

    def guarded(text: str) -> dict[str, object]:
        assert len(text) <= MAX, "oversized file reached the parser"
        return real_loads(text)

    monkeypatch.setattr("app.forms.loader.tomllib.loads", guarded)
    assert codes(scan(tmp_path)) == {DiagnosticCode.FILE_TOO_LARGE}


def test_file_exactly_at_limit_is_accepted(tmp_path: Path) -> None:
    package = write_package(tmp_path, FORM_A, "room-booking")
    content = "schema_version = 1\n"
    (package / "elements.toml").write_text(content + "#" * (MAX - len(content) - 1) + "\n")
    assert len(scan(tmp_path).forms) == 1


def test_duplicate_slug_rejects_both(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    write_package(tmp_path, FORM_B, "room-booking")
    write_package(tmp_path, FORM_C, "contact")
    result = scan(tmp_path)
    assert [f.id for f in result.forms] == [FORM_C]
    dupes = [(d.relative_path, d.code) for d in result.diagnostics]
    assert dupes == [
        (FORM_A, DiagnosticCode.DUPLICATE_SLUG),
        (FORM_B, DiagnosticCode.DUPLICATE_SLUG),
    ]
    assert FORM_B in result.diagnostics[0].message and FORM_A in result.diagnostics[1].message


def _package(form_id: str, slug: str, rel: str) -> FormPackage:
    return FormPackage(
        id=form_id,
        slug=slug,
        title="Reserva de sala",
        subtitle=None,
        description=None,
        status="draft",
        schema_version=1,
        relative_path=rel,
        package_path=Path("/unused") / rel,
    )


def test_duplicate_form_id_rejects_all_participants() -> None:
    # Only reachable through inconsistent metadata (e.g. case-insensitive filesystems).
    forms, diagnostics = resolve_conflicts(
        [_package(FORM_A, "one", "a1"), _package(FORM_A, "two", "a2"), _package(FORM_B, "b", "b")]
    )
    assert [f.id for f in forms] == [FORM_B]
    assert {(d.relative_path, d.code) for d in diagnostics} == {
        ("a1", DiagnosticCode.DUPLICATE_FORM_ID),
        ("a2", DiagnosticCode.DUPLICATE_FORM_ID),
    }


def test_invalid_package_does_not_block_valid_one(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "room-booking")
    write_package(tmp_path, FORM_B, "broken", form="this is = = not toml")
    result = scan(tmp_path)
    assert [f.id for f in result.forms] == [FORM_A]
    assert only_codes_for(result, FORM_B) == {DiagnosticCode.INVALID_TOML}
    assert result.packages_seen == 2
