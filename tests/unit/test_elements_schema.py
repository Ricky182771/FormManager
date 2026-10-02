"""elements.toml schema v1: the strict parser (no payloads here, see test_answers.py)."""

from __future__ import annotations

import dataclasses
import tomllib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from app.forms.diagnostics import DiagnosticCode
from app.forms.elements import (
    MAX_ELEMENTS,
    DateTimeElement,
    DecimalElement,
    ElementsSchema,
    MultiSelectElement,
    Normalization,
    Option,
    SelectElement,
    TextElement,
    parse_elements,
)
from app.forms.loader import scan_forms_dir
from tests.forms_fixtures import FORM_A, element_toml, elements_toml, write_package

Problems = list[tuple[DiagnosticCode, str]]


def parse(*elements: str) -> tuple[ElementsSchema | None, Problems]:
    return parse_elements(tomllib.loads(elements_toml(*elements)))


def schema(*elements: str) -> ElementsSchema:
    result, problems = parse(*elements)
    assert problems == []
    assert result is not None
    return result


def codes(*elements: str) -> set[DiagnosticCode]:
    result, problems = parse(*elements)
    assert result is None
    return {code for code, _ in problems}


OPTIONS = '[[element.options]]\nvalue = "am"\nlabel = "Matutina"\n'
OPTIONS += '[[element.options]]\nvalue = "pm"\nlabel = "Vespertina"\n'

# schema_version and the root


@pytest.mark.parametrize(
    ("version", "accepted"), [("1", True), ("true", False), ("2", False), ('"1"', False)]
)
def test_schema_version(tmp_path: Path, version: str, accepted: bool) -> None:
    write_package(tmp_path, FORM_A, "room-booking", elements=f"schema_version = {version}\n")
    result = scan_forms_dir(tmp_path, 64 * 1024)
    assert (len(result.forms) == 1) is accepted
    if not accepted:
        assert {d.code for d in result.diagnostics} == {DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION}


def test_zero_elements_is_a_valid_schema() -> None:
    assert schema() == ElementsSchema()
    assert parse_elements({"schema_version": 1, "element": []}) == (ElementsSchema(), [])


def test_unknown_root_key() -> None:
    _, problems = parse_elements({"schema_version": 1, "fields": []})
    assert problems == [(DiagnosticCode.INVALID_ELEMENTS_SCHEMA, "Propiedad desconocida fields.")]


@pytest.mark.parametrize("value", ["x", 1, ["x"], {"id": "a"}])
def test_element_must_be_an_array_of_tables(value: object) -> None:
    _, problems = parse_elements({"schema_version": 1, "element": value})
    assert [code for code, _ in problems] == [DiagnosticCode.INVALID_ELEMENTS_SCHEMA]


def test_element_count_limit() -> None:
    many = [element_toml(f"f{i}") for i in range(MAX_ELEMENTS)]
    assert len(schema(*many).elements) == MAX_ELEMENTS
    assert codes(*many, element_toml("extra")) == {DiagnosticCode.TOO_MANY_ELEMENTS}


# common properties


@pytest.mark.parametrize("element_id", ["email", "student_email", "member-2", "a", "a" * 64])
def test_valid_element_ids(element_id: str) -> None:
    assert schema(element_toml(element_id)).elements[0].id == element_id


@pytest.mark.parametrize(
    "element_id",
    [
        "Email",
        "2fa",
        "_x",
        "-x",
        "x_",
        "a__b",
        "a-_b",
        "a.b",
        "a/b",
        "a b",
        "émail",
        "еmail",  # Cyrillic "е"
        "ｅmail",  # fullwidth
        "a" * 65,
        "",
    ],
)
def test_invalid_element_ids(element_id: str) -> None:
    assert codes(element_toml(element_id)) == {DiagnosticCode.INVALID_ELEMENT_ID}


def test_element_id_must_be_a_string() -> None:
    text = element_toml().replace('id = "field"', "id = 7")
    assert codes(text) == {DiagnosticCode.INVALID_ELEMENT_ID}


def test_duplicate_element_id() -> None:
    _, problems = parse(element_toml("email"), element_toml("email", "email"))
    assert [code for code, _ in problems] == [DiagnosticCode.DUPLICATE_ELEMENT_ID]
    assert "Elemento 2" in problems[0][1]


def test_ids_differing_only_by_separator_are_distinct() -> None:
    assert len(schema(element_toml("a_b"), element_toml("a-b")).elements) == 2


@pytest.mark.parametrize("prop", ["id", "type", "label", "required"])
def test_missing_common_property(prop: str) -> None:
    lines = [line for line in element_toml().splitlines() if not line.startswith(f"{prop} =")]
    assert codes("\n".join(lines) + "\n") == {DiagnosticCode.MISSING_ELEMENT_PROPERTY}


@pytest.mark.parametrize("value", ['"yes"', "1", "0", '"true"'])
def test_required_must_be_a_real_bool(value: str) -> None:
    text = element_toml().replace("required = true", f"required = {value}")
    assert codes(text) == {DiagnosticCode.INVALID_ELEMENT_PROPERTY}


@pytest.mark.parametrize("label", ["", "   ", "x" * 201, "a\nb", "a\tb", "a\x00b"])
def test_invalid_label(label: str) -> None:
    assert codes(element_toml(label=label)) == {DiagnosticCode.INVALID_ELEMENT_PROPERTY}


def test_label_is_kept_as_source_text() -> None:
    assert schema(element_toml(label="Correo **electrónico**")).elements[0].label == (
        "Correo **electrónico**"
    )


@pytest.mark.parametrize("description", ['""', '"   "', '"' + "x" * 2001 + '"', '"a\\u0000b"'])
def test_invalid_description(description: str) -> None:
    text = element_toml(extra=f"description = {description}\n")
    assert codes(text) == {DiagnosticCode.INVALID_ELEMENT_PROPERTY}


def test_description_allows_lf_and_tab() -> None:
    text = element_toml(extra='description = """\nLínea uno\n\tLínea dos"""\n')
    assert schema(text).elements[0].description == "Línea uno\n\tLínea dos"


# types


@pytest.mark.parametrize(
    "element_type", ["checkbox", "radio", "dropdown", "toggle", "textarea", "date-picker", "Text"]
)
def test_widgets_and_unknown_types_are_rejected(element_type: str) -> None:
    assert codes(element_toml(element_type=element_type)) == {DiagnosticCode.UNKNOWN_ELEMENT_TYPE}


def test_type_must_be_a_string() -> None:
    text = element_toml().replace('type = "text"', "type = 3")
    assert codes(text) == {DiagnosticCode.UNKNOWN_ELEMENT_TYPE}


@pytest.mark.parametrize("element_type", ["resource_select", "resource_multi_select"])
def test_resource_backed_types_are_recognised_but_unsupported(element_type: str) -> None:
    _, problems = parse(element_toml(element_type=element_type, extra='resource = "rooms"\n'))
    assert [code for code, _ in problems] == [DiagnosticCode.UNSUPPORTED_ELEMENT_TYPE]
    assert "Resources" in problems[0][1]


# properties


def test_unknown_property_is_named() -> None:
    _, problems = parse(element_toml("name", extra='banana = "yes"\n'))
    assert problems == [
        (
            DiagnosticCode.UNKNOWN_ELEMENT_PROPERTY,
            "Elemento 1 (name): propiedad desconocida banana.",
        )
    ]


@pytest.mark.parametrize("prop", ["default", "placeholder", "help_url", "kind", "widget", "color"])
def test_properties_outside_the_contract_are_unknown(prop: str) -> None:
    assert codes(element_toml(extra=f'{prop} = "x"\n')) == {DiagnosticCode.UNKNOWN_ELEMENT_PROPERTY}


def test_pattern_is_deferred() -> None:
    _, problems = parse(element_toml(extra='pattern = "(a+)+$"\n'))
    assert [code for code, _ in problems] == [DiagnosticCode.UNSUPPORTED_ELEMENT_PROPERTY]
    assert "diferido" in problems[0][1]


@pytest.mark.parametrize(
    ("element_type", "extra"),
    [
        ("email", "min = 10\n"),
        ("integer", "min_length = 1\n"),
        ("boolean", "max = 1\n"),
        ("text", "min_selected = 1\n"),
        ("select", "max_length = 3\n" + OPTIONS),
        ("date", "decimal_places = 2\n"),
        ("url", "max_length = 10\n"),
    ],
)
def test_incompatible_constraint(element_type: str, extra: str) -> None:
    assert codes(element_toml(element_type=element_type, extra=extra)) == {
        DiagnosticCode.INVALID_CONSTRAINT
    }


def test_normalize_on_a_type_without_normalization() -> None:
    text = element_toml(element_type="integer", extra="[element.normalize]\ntrim = true\n")
    assert codes(text) == {DiagnosticCode.INVALID_NORMALIZATION}


def test_options_on_a_type_without_options() -> None:
    assert codes(element_toml(element_type="integer", extra=OPTIONS)) == {
        DiagnosticCode.INVALID_OPTIONS
    }


# text and text_long


def test_text_defaults_to_the_hard_maximum() -> None:
    [short] = schema(element_toml()).elements
    [long] = schema(element_toml(element_type="text_long")).elements
    assert isinstance(short, TextElement) and isinstance(long, TextElement)
    assert (short.max_length, long.max_length) == (1000, 10_000)
    assert short.min_length is None and short.normalize == Normalization()


@pytest.mark.parametrize(
    ("element_type", "extra", "valid"),
    [
        ("text", "max_length = 1000\n", True),
        ("text", "max_length = 1001\n", False),
        ("text_long", "max_length = 10000\n", True),
        ("text_long", "max_length = 10001\n", False),
        ("text", "min_length = 1\n", True),
        ("text", "min_length = 0\n", False),
        ("text", "min_length = 5\nmax_length = 5\n", True),
        ("text", "min_length = 6\nmax_length = 5\n", False),
        ("text", "min_length = 1001\n", False),
        ("text", "max_length = true\n", False),
        ("text", 'max_length = "10"\n', False),
        ("text", "max_length = 10.0\n", False),
    ],
)
def test_text_length_constraints(element_type: str, extra: str, valid: bool) -> None:
    text = element_toml(element_type=element_type, extra=extra)
    if valid:
        schema(text)
    else:
        assert codes(text) == {DiagnosticCode.INVALID_CONSTRAINT}


def test_normalize_key_order_in_toml_does_not_matter() -> None:
    first = schema(
        element_toml(
            extra='[element.normalize]\ncase = "upper"\ncollapse_whitespace = true\ntrim = true\n'
        )
    )
    second = schema(
        element_toml(
            extra='[element.normalize]\ntrim = true\ncollapse_whitespace = true\ncase = "upper"\n'
        )
    )
    assert first == second
    assert first.elements[0].normalize == Normalization(True, True, "upper")  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("element_type", "normalize"),
    [
        ("text", "strip = true"),
        ("text", "trim = 1"),
        ("text", 'trim = "yes"'),
        ("text", 'case = "title"'),
        ("text", "case = true"),
        ("text", 'unicode = "NFKC"'),
        ("text_long", "collapse_whitespace = true"),
        ("text_long", "collapse_whitespace = false"),
        ("email", "collapse_whitespace = true"),
        ("email", 'case = "upper"'),
    ],
)
def test_invalid_normalization(element_type: str, normalize: str) -> None:
    text = element_toml(element_type=element_type, extra=f"[element.normalize]\n{normalize}\n")
    assert codes(text) == {DiagnosticCode.INVALID_NORMALIZATION}


def test_normalize_must_be_a_table() -> None:
    assert codes(element_toml(extra="normalize = true\n")) == {DiagnosticCode.INVALID_NORMALIZATION}


@pytest.mark.parametrize(
    ("element_type", "normalize"),
    [("text_long", 'trim = true\ncase = "lower"'), ("email", 'trim = true\ncase = "lower"')],
)
def test_allowed_normalizations(element_type: str, normalize: str) -> None:
    schema(element_toml(element_type=element_type, extra=f"[element.normalize]\n{normalize}\n"))


# integer and decimal


@pytest.mark.parametrize(
    ("extra", "valid"),
    [
        ("min = 0\nmax = 120\n", True),
        ("min = 5\nmax = 5\n", True),
        ("min = 6\nmax = 5\n", False),
        ("min = true\n", False),
        ("min = 1.0\n", False),
        ('min = "1"\n', False),
        (f"max = {2**63 - 1}\nmin = {-(2**63)}\n", True),
    ],
)
def test_integer_bounds(extra: str, valid: bool) -> None:
    text = element_toml(element_type="integer", extra=extra)
    if valid:
        schema(text)
    else:
        assert codes(text) == {DiagnosticCode.INVALID_CONSTRAINT}


def test_integer_bound_outside_int64_is_rejected() -> None:
    # tomllib accepts arbitrarily large integers; the schema does not.
    document = tomllib.loads(elements_toml(element_toml(element_type="integer")))
    document["element"][0]["max"] = 2**63
    _, problems = parse_elements(document)
    assert [code for code, _ in problems] == [DiagnosticCode.INVALID_CONSTRAINT]


def test_decimal_requires_decimal_places() -> None:
    assert codes(element_toml(element_type="decimal")) == {DiagnosticCode.MISSING_ELEMENT_PROPERTY}


@pytest.mark.parametrize(
    ("extra", "valid"),
    [
        ("decimal_places = 0\n", True),
        ("decimal_places = 18\n", True),
        ("decimal_places = 19\n", False),
        ("decimal_places = -1\n", False),
        ("decimal_places = true\n", False),
        ('decimal_places = 2\nmin = "0"\nmax = "99.99"\n', True),
        ('decimal_places = 2\nmin = "1.234"\n', False),
        ("decimal_places = 2\nmin = 1.5\n", False),
        ("decimal_places = 2\nmin = 1\n", False),
        ('decimal_places = 2\nmin = "1e2"\n', False),
        ('decimal_places = 2\nmin = "5"\nmax = "4.99"\n', False),
    ],
)
def test_decimal_constraints(extra: str, valid: bool) -> None:
    text = element_toml(element_type="decimal", extra=extra)
    if valid:
        schema(text)
    else:
        assert codes(text) == {DiagnosticCode.INVALID_CONSTRAINT}


def test_decimal_bounds_are_canonical_decimals() -> None:
    text = element_toml(element_type="decimal", extra='decimal_places = 2\nmin = "1.5"\n')
    [element] = schema(text).elements
    assert isinstance(element, DecimalElement)
    assert element.min == Decimal("1.50") and str(element.min) == "1.50"
    assert element.max is None


# date, time, datetime bounds are native TOML values


@pytest.mark.parametrize(
    ("element_type", "extra", "valid"),
    [
        ("date", "min = 2026-01-01\nmax = 2026-12-31\n", True),
        ("date", 'min = "2026-01-01"\n', False),
        ("date", "min = 2026-01-01T00:00:00Z\n", False),
        ("date", "min = 2026-12-31\nmax = 2026-01-01\n", False),
        ("time", "min = 08:00:00\nmax = 18:00:00\n", True),
        ("time", "min = 08:00:00.5\n", False),
        ("time", 'min = "08:00"\n', False),
        ("datetime", "min = 2026-10-02T08:00:00-06:00\n", True),
        ("datetime", "min = 2026-10-02T08:00:00\n", False),
        ("datetime", "min = 2026-10-02T08:00:00.25Z\n", False),
        ("datetime", "min = 2026-10-02\n", False),
        ("datetime", "min = 2026-10-02T10:00:00Z\nmax = 2026-10-02T05:00:00-04:00\n", False),
    ],
)
def test_temporal_bounds(element_type: str, extra: str, valid: bool) -> None:
    text = element_toml(element_type=element_type, extra=extra)
    if valid:
        schema(text)
    else:
        assert codes(text) == {DiagnosticCode.INVALID_CONSTRAINT}


def test_datetime_bounds_are_stored_in_utc() -> None:
    text = element_toml(element_type="datetime", extra="min = 2026-10-02T18:30:00-06:00\n")
    [element] = schema(text).elements
    assert isinstance(element, DateTimeElement)
    assert element.min == datetime(2026, 10, 3, 0, 30, tzinfo=UTC)
    assert element.min is not None and element.min.tzinfo is UTC


def test_temporal_bound_types() -> None:
    [d] = schema(element_toml(element_type="date", extra="min = 2026-01-01\n")).elements
    [t] = schema(element_toml(element_type="time", extra="min = 08:00:00\n")).elements
    assert d.min == date(2026, 1, 1) and t.min == time(8, 0)  # type: ignore[union-attr]


# select and multi_select


def test_select_options_keep_declaration_order() -> None:
    [element] = schema(element_toml("session", "select", extra=OPTIONS)).elements
    assert isinstance(element, SelectElement)
    assert element.options == (Option("am", "Matutina"), Option("pm", "Vespertina"))


def test_select_requires_options() -> None:
    assert codes(element_toml(element_type="select")) == {DiagnosticCode.MISSING_ELEMENT_PROPERTY}


@pytest.mark.parametrize(
    "options",
    [
        "options = []\n",
        'options = "am"\n',
        '[[element.options]]\nvalue = "am"\nlabel = "A"\nicon = "sun"\n',
        '[[element.options]]\nvalue = "AM"\nlabel = "A"\n',
        '[[element.options]]\nvalue = "a m"\nlabel = "A"\n',
        '[[element.options]]\nvalue = 1\nlabel = "A"\n',
        '[[element.options]]\nvalue = true\nlabel = "A"\n',
        '[[element.options]]\nvalue = "' + "a" * 65 + '"\nlabel = "A"\n',
        '[[element.options]]\nvalue = "am"\n',
        '[[element.options]]\nvalue = "am"\nlabel = " "\n',
        '[[element.options]]\nlabel = "A"\n',
    ],
)
def test_invalid_options(options: str) -> None:
    assert codes(element_toml(element_type="select", extra=options)) == {
        DiagnosticCode.INVALID_OPTIONS
    }


def test_option_limit() -> None:
    many = "".join(f'[[element.options]]\nvalue = "o{i}"\nlabel = "O{i}"\n' for i in range(201))
    assert codes(element_toml(element_type="select", extra=many)) == {
        DiagnosticCode.INVALID_OPTIONS
    }


@pytest.mark.parametrize("value", ["am", "room_a", "room-2", "2026", "a" * 64])
def test_valid_option_values(value: str) -> None:
    schema(
        element_toml(
            element_type="select",
            extra=f'[[element.options]]\nvalue = "{value}"\n' 'label = "Opción"\n',
        )
    )


def test_duplicate_option_value() -> None:
    options = OPTIONS + '[[element.options]]\nvalue = "am"\nlabel = "Otra"\n'
    assert codes(element_toml(element_type="select", extra=options)) == {
        DiagnosticCode.DUPLICATE_OPTION_VALUE
    }


def test_duplicate_option_label() -> None:
    options = OPTIONS + '[[element.options]]\nvalue = "night"\nlabel = "Matutina"\n'
    assert codes(element_toml(element_type="multi_select", extra=options)) == {
        DiagnosticCode.DUPLICATE_OPTION_LABEL
    }


@pytest.mark.parametrize(
    ("bounds", "valid"),
    [
        ("min_selected = 1\nmax_selected = 2\n", True),
        ("min_selected = 2\nmax_selected = 2\n", True),
        ("min_selected = 0\n", False),
        ("max_selected = 3\n", False),
        ("min_selected = 2\nmax_selected = 1\n", False),
        ("min_selected = true\n", False),
    ],
)
def test_multi_select_bounds(bounds: str, valid: bool) -> None:
    text = element_toml(element_type="multi_select", extra=bounds + OPTIONS)
    if valid:
        [element] = schema(text).elements
        assert isinstance(element, MultiSelectElement)
    else:
        assert codes(text) == {DiagnosticCode.INVALID_CONSTRAINT}


# the in-memory model


def test_schema_is_immutable() -> None:
    built = schema(element_toml("email", "email"))
    element = built.elements[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        element.required = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        built.by_id["other"] = element  # type: ignore[index]
    assert built.by_id["email"] is element


def test_all_problems_of_an_element_are_reported() -> None:
    text = element_toml(label="", extra="banana = 1\nmax_length = 0\n").replace(
        "required = true", 'required = "si"'
    )
    assert codes(text) == {
        DiagnosticCode.INVALID_ELEMENT_PROPERTY,
        DiagnosticCode.UNKNOWN_ELEMENT_PROPERTY,
        DiagnosticCode.INVALID_CONSTRAINT,
    }
