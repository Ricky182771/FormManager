"""Hardening of elements.toml parsing and answer validation."""

from __future__ import annotations

import time
import tomllib
from pathlib import Path

import pytest

from app.forms.answers import AnswerErrorCode, validate_answers
from app.forms.diagnostics import DiagnosticCode
from app.forms.elements import ElementsSchema, parse_elements
from app.forms.loader import scan_forms_dir
from tests.forms_fixtures import FORM_A, element_toml, elements_toml, write_package

E = AnswerErrorCode
SECRET = "alice-secret-token-123"


def build(*elements: str) -> ElementsSchema:
    schema, problems = parse_elements(tomllib.loads(elements_toml(*elements)))
    assert problems == [] and schema is not None
    return schema


OPTIONS = '[[element.options]]\nvalue = "am"\nlabel = "Matutina"\n'


@pytest.mark.parametrize(
    ("element_type", "extra", "value"),
    [
        ("text", "max_length = 5\n", SECRET),
        ("text", "", f"{SECRET}\n"),
        ("email", "", f"{SECRET}@exa mple.com"),
        ("url", "", f"https://{SECRET}@example.com"),
        ("integer", "", SECRET),
        ("decimal", "decimal_places = 2\n", SECRET),
        ("date", "", SECRET),
        ("datetime", "", SECRET),
        ("select", OPTIONS, SECRET),
        ("multi_select", OPTIONS, [SECRET]),
    ],
)
def test_errors_never_echo_the_input(element_type: str, extra: str, value: object) -> None:
    schema = build(element_toml("field", element_type, extra=extra))
    result = validate_answers(schema, {"field": value})
    assert not result.valid
    assert SECRET not in repr(result)


def test_errors_never_echo_labels() -> None:
    schema = build(element_toml("field", label="Etiqueta privada ALICE EXAMPLE"))
    result = validate_answers(schema, {})
    assert "ALICE" not in repr(result)


@pytest.mark.parametrize(
    "key", ["../../etc/passwd", "<script>alert(1)</script>", "A" * 500, "Email", "a b", "é"]
)
def test_unsafe_unknown_keys_are_not_echoed(key: str) -> None:
    result = validate_answers(ElementsSchema(), {key: SECRET})
    [error] = result.errors
    assert (error.element_id, error.code) == (None, E.UNKNOWN_FIELD)
    assert key not in repr(result) and SECRET not in repr(result)


def test_many_unknown_fields_are_capped() -> None:
    result = validate_answers(ElementsSchema(), {f"k{i}": i for i in range(5000)})
    assert len(result.errors) == 20


@pytest.mark.parametrize(
    ("element_type", "value", "code"),
    [
        ("text", "x" * 1_000_000, E.TOO_LONG),
        ("text_long", "x" * 1_000_000, E.TOO_LONG),
        ("email", "a" * 1_000_000 + "@example.com", E.TOO_LONG),
        ("url", "https://example.com/" + "a" * 1_000_000, E.TOO_LONG),
        ("text", "\x00" * 1_000_000, E.INVALID_CHARACTERS),
    ],
)
def test_oversized_strings_are_rejected_quickly(
    element_type: str, value: str, code: AnswerErrorCode
) -> None:
    schema = build(element_toml("field", element_type))
    started = time.perf_counter()
    [error] = validate_answers(schema, {"field": value}).errors
    assert error.code == code
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("element_type", "value"),
    [
        ("email", "a" + ".a" * 120 + "@" + "a." * 120 + "!"),
        ("email", "a" * 60 + "@" + "a-" * 90 + "!"),
        ("url", "https://" + "a." * 900 + "-"),
        ("url", "https://example.com/" + "%a" * 900),
        ("url", "https://example.com/?" + "%2" * 600),
        ("datetime", "2026-10-02T18:30:00" + "0" * 2000),
    ],
)
def test_builtin_formats_resist_backtracking(element_type: str, value: str) -> None:
    schema = build(element_toml("field", element_type))
    started = time.perf_counter()
    [error] = validate_answers(schema, {"field": value}).errors
    assert error.code in (E.INVALID_FORMAT, E.TOO_LONG)
    assert time.perf_counter() - started < 0.5


def test_author_regex_is_not_accepted_at_all() -> None:
    # pattern is deferred: a catastrophic pattern never reaches re.compile.
    text = elements_toml(element_toml(extra='pattern = "^(a+)+$"\n'))
    _, problems = parse_elements(tomllib.loads(text))
    assert [code for code, _ in problems] == [DiagnosticCode.UNSUPPORTED_ELEMENT_PROPERTY]


@pytest.mark.parametrize(
    ("element_type", "extra", "value"),
    [
        ("integer", "", True),
        ("integer", "", False),
        ("boolean", "", 1),
        ("boolean", "", 0),
        ("decimal", "decimal_places = 2\n", True),
        ("text", "", 0),
    ],
)
def test_bool_int_confusion(element_type: str, extra: str, value: object) -> None:
    schema = build(element_toml("field", element_type, extra=extra))
    [error] = validate_answers(schema, {"field": value}).errors
    assert error.code == E.INVALID_TYPE


@pytest.mark.parametrize("value", [chr(0xD800), f"a{chr(0xDFFF)}b", chr(0xDC00) + chr(0xDBFF)])
@pytest.mark.parametrize("element_type", ["text", "text_long"])
def test_lone_surrogates_are_rejected(element_type: str, value: str) -> None:
    schema = build(element_toml("field", element_type))
    [error] = validate_answers(schema, {"field": value}).errors
    assert error.code == E.INVALID_CHARACTERS


def test_non_ascii_email_and_url_are_rejected_before_parsing() -> None:
    schema = build(element_toml("mail", "email"), element_toml("site", "url"))
    result = validate_answers(schema, {"mail": "a\x00@example.com", "site": "https://e\u202e.com"})
    assert [e.code for e in result.errors] == [E.INVALID_FORMAT, E.INVALID_FORMAT]


def test_schema_diagnostics_have_no_paths_or_property_values(tmp_path: Path) -> None:
    bad = elements_toml(
        element_toml("a", extra=f'banana = "{SECRET}"\n'),
        element_toml("a", "../../etc/passwd"),
        element_toml("b", label=SECRET + "\x00"),
    )
    write_package(tmp_path, FORM_A, "room-booking", elements=bad)
    result = scan_forms_dir(tmp_path, 64 * 1024)
    assert result.forms == ()
    text = repr(result.diagnostics)
    assert str(tmp_path) not in text and SECRET not in text
    assert {d.code for d in result.diagnostics} == {
        DiagnosticCode.UNKNOWN_ELEMENT_PROPERTY,
        DiagnosticCode.DUPLICATE_ELEMENT_ID,
        DiagnosticCode.UNKNOWN_ELEMENT_TYPE,
        DiagnosticCode.INVALID_ELEMENT_PROPERTY,
    }
    # Names from the file are escaped before they reach a message.
    assert "'../../etc/passwd'" in text


def test_elements_diagnostics_are_capped_per_file(tmp_path: Path) -> None:
    bad = elements_toml(*(element_toml(f"f{i}", "checkbox") for i in range(60)))
    write_package(tmp_path, FORM_A, "room-booking", elements=bad)
    assert len(scan_forms_dir(tmp_path, 64 * 1024).diagnostics) == 20
