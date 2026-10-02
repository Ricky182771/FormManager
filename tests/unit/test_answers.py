"""validate_answers: per-type semantics, presence rules, normalization and canonical values."""

from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime, time
from decimal import Decimal, localcontext

import pytest

from app.forms.answers import (
    MAX_ERRORS,
    AnswerErrorCode,
    CanonicalValue,
    ValidationResult,
    validate_answers,
)
from app.forms.elements import ElementsSchema, parse_elements
from tests.forms_fixtures import element_toml, elements_toml

E = AnswerErrorCode


def build(*elements: str) -> ElementsSchema:
    schema, problems = parse_elements(tomllib.loads(elements_toml(*elements)))
    assert problems == [] and schema is not None
    return schema


def field(element_type: str = "text", extra: str = "", *, required: bool = True) -> ElementsSchema:
    return build(element_toml("field", element_type, required=required, extra=extra))


def ok(schema: ElementsSchema, value: object) -> CanonicalValue:
    result = validate_answers(schema, {"field": value})
    assert result.errors == (), result.errors
    assert result.valid
    return result.values["field"]


def err(schema: ElementsSchema, value: object) -> tuple[AnswerErrorCode, str | None]:
    result = validate_answers(schema, {"field": value})
    assert not result.valid and result.values == {}
    [error] = result.errors
    assert error.element_id == "field"
    return error.code, error.constraint


def omitted(schema: ElementsSchema, value: object) -> bool:
    result = validate_answers(schema, {"field": value})
    return result.valid and "field" not in result.values


NORMALIZE = "[element.normalize]\n"
OPTIONS = '[[element.options]]\nvalue = "am"\nlabel = "Matutina"\n'
OPTIONS += '[[element.options]]\nvalue = "pm"\nlabel = "Vespertina"\n'
OPTIONS += '[[element.options]]\nvalue = "night"\nlabel = "Nocturna"\n'


# The example from the Hito 2 brief.


def test_conceptual_example() -> None:
    schema = build(
        element_toml("contact_email", "email", label="Correo"),
        element_toml("age", "integer", label="Edad", extra="min = 0\nmax = 120\n"),
        element_toml("session", "select", label="Sesión", extra=OPTIONS),
    )
    result = validate_answers(
        schema, {"contact_email": "alice@example.com", "age": 18, "session": "am"}
    )
    assert result == ValidationResult(
        True, {"contact_email": "alice@example.com", "age": 18, "session": "am"}, ()
    )


# Presence: absent, null, blank, unknown


ALL_TYPES = {
    "text": "",
    "text_long": "",
    "integer": "",
    "decimal": "decimal_places = 2\n",
    "boolean": "",
    "email": "",
    "url": "",
    "date": "",
    "time": "",
    "datetime": "",
    "select": OPTIONS,
    "multi_select": OPTIONS,
}


@pytest.mark.parametrize(("element_type", "extra"), ALL_TYPES.items())
def test_absent_required_field(element_type: str, extra: str) -> None:
    result = validate_answers(field(element_type, extra), {})
    assert [(e.element_id, e.code, e.constraint) for e in result.errors] == [
        ("field", E.FIELD_REQUIRED, "required")
    ]


@pytest.mark.parametrize(("element_type", "extra"), ALL_TYPES.items())
def test_absent_optional_field_is_omitted(element_type: str, extra: str) -> None:
    assert validate_answers(field(element_type, extra, required=False), {}) == ValidationResult(
        True, {}, ()
    )


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize(("element_type", "extra"), ALL_TYPES.items())
def test_null_is_never_absence(element_type: str, extra: str, required: bool) -> None:
    assert err(field(element_type, extra, required=required), None) == (E.INVALID_TYPE, None)


STRING_TYPES = {
    k: v for k, v in ALL_TYPES.items() if k not in ("integer", "boolean", "multi_select")
}


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n", "\r\n", "\u00a0", "\u3000"])
@pytest.mark.parametrize(("element_type", "extra"), STRING_TYPES.items())
def test_blank_string_is_no_answer(element_type: str, extra: str, blank: str) -> None:
    assert err(field(element_type, extra), blank) == (E.FIELD_REQUIRED, "required")
    assert omitted(field(element_type, extra, required=False), blank)


def test_blank_is_decided_before_character_rules() -> None:
    # TAB is invalid inside a `text` answer, but a TAB-only answer is simply "not answered".
    assert omitted(field(required=False), "\t")
    assert err(field(), "a\tb") == (E.INVALID_CHARACTERS, None)


def test_blank_does_not_trim_a_real_answer() -> None:
    assert ok(field(), "  hola  ") == "  hola  "


def test_unknown_fields_are_rejected_after_element_errors() -> None:
    schema = build(element_toml("name"), element_toml("age", "integer"))
    result = validate_answers(schema, {"zeta": 1, "name": "ALICE EXAMPLE", "alpha": 2})
    assert not result.valid and result.values == {}
    assert [(e.element_id, e.code) for e in result.errors] == [
        ("age", E.FIELD_REQUIRED),
        ("alpha", E.UNKNOWN_FIELD),
        ("zeta", E.UNKNOWN_FIELD),
    ]


def test_any_error_discards_every_canonical_value() -> None:
    schema = build(element_toml("name"), element_toml("age", "integer"))
    result = validate_answers(schema, {"name": "ALICE EXAMPLE", "age": "18"})
    assert result.values == {}
    assert [(e.element_id, e.code) for e in result.errors] == [("age", E.INVALID_TYPE)]


def test_at_most_one_error_per_element_and_twenty_overall() -> None:
    schema = build(*(element_toml(f"f{i}", "integer", extra="min = 10\n") for i in range(30)))
    result = validate_answers(schema, {f"f{i}": "x" for i in range(30)} | {"extra": 1})
    assert len(result.errors) == MAX_ERRORS
    assert [e.element_id for e in result.errors] == [f"f{i}" for i in range(MAX_ERRORS)]


@pytest.mark.parametrize("payload", [None, [], ["field"], "field", 1, True])
def test_payload_must_be_an_object(payload: object) -> None:
    result = validate_answers(field(), payload)
    assert [(e.element_id, e.code) for e in result.errors] == [(None, E.INVALID_PAYLOAD)]


def test_empty_schema_accepts_only_an_empty_object() -> None:
    assert validate_answers(ElementsSchema(), {}).valid
    assert not validate_answers(ElementsSchema(), {"x": 1}).valid


def test_values_are_read_only() -> None:
    result = validate_answers(field(), {"field": "x"})
    with pytest.raises(TypeError):
        result.values["field"] = "y"  # type: ignore[index]


# text


def test_text_accepts_unicode_and_keeps_it() -> None:
    assert ok(field(), "Ñandú 🦤 日本語") == "Ñandú 🦤 日本語"


@pytest.mark.parametrize("value", [5, 5.0, True, ["a"], {"a": 1}])
def test_text_wrong_type(value: object) -> None:
    assert err(field(), value) == (E.INVALID_TYPE, None)


@pytest.mark.parametrize(
    "value",
    ["a\nb", "a\rb", "a\tb", "a\x00b", "a\x1bb", "a\x7fb", "a\x85b", "a\x9fb", "a\ud800b"],
)
def test_text_rejects_line_breaks_tabs_controls_and_surrogates(value: str) -> None:
    assert err(field(), value) == (E.INVALID_CHARACTERS, None)


def test_text_length_boundaries() -> None:
    schema = field(extra="min_length = 2\nmax_length = 4\n")
    assert ok(schema, "ab") == "ab"
    assert ok(schema, "abcd") == "abcd"
    assert err(schema, "a") == (E.TOO_SHORT, "min_length")
    assert err(schema, "abcde") == (E.TOO_LONG, "max_length")


def test_text_hard_maximum_applies_without_max_length() -> None:
    assert ok(field(), "x" * 1000) == "x" * 1000
    assert err(field(), "x" * 1001) == (E.TOO_LONG, "max_length")


def test_length_counts_code_points_not_utf16_units() -> None:
    # An emoji is one code point here (HTML maxlength would count two UTF-16 units).
    assert ok(field(extra="max_length = 1\n"), "🦤") == "🦤"


# text_long


def test_text_long_canonicalizes_line_endings() -> None:
    assert ok(field("text_long"), "a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_text_long_allows_lf_and_tab() -> None:
    assert ok(field("text_long"), "uno\n\tdos") == "uno\n\tdos"


@pytest.mark.parametrize("value", ["a\x00b", "a\x0bb", "a\x0cb", "a\x7fb", "a\x85b", "a\udc00b"])
def test_text_long_rejects_other_controls(value: str) -> None:
    assert err(field("text_long"), value) == (E.INVALID_CHARACTERS, None)


def test_text_long_length_is_measured_after_crlf_canonicalization() -> None:
    assert ok(field("text_long", "max_length = 3\n"), "a\r\nb") == "a\nb"


def test_text_long_hard_maximum() -> None:
    assert ok(field("text_long"), "x" * 10_000) == "x" * 10_000
    assert err(field("text_long"), "x" * 10_001) == (E.TOO_LONG, "max_length")


def test_text_long_trim_removes_outer_line_breaks() -> None:
    schema = field("text_long", NORMALIZE + "trim = true\n")
    assert ok(schema, "\n\n línea \n  dos \n") == "línea \n  dos"


# normalization and its order


def test_trim() -> None:
    assert ok(field(extra=NORMALIZE + "trim = true\n"), "  alice  ") == "alice"


def test_trim_removes_unicode_whitespace() -> None:
    assert ok(field(extra=NORMALIZE + "trim = true\n"), "\u00a0\u3000alice\u2003") == "alice"


def test_collapse_whitespace_without_trim_keeps_one_outer_space() -> None:
    schema = field(extra=NORMALIZE + "collapse_whitespace = true\n")
    assert ok(schema, "  alice \u3000 example ") == " alice example "


@pytest.mark.parametrize(("case", "expected"), [("lower", "ñandú"), ("upper", "ÑANDÚ")])
def test_case(case: str, expected: str) -> None:
    assert ok(field(extra=NORMALIZE + f'case = "{case}"\n'), "Ñandú") == expected


def test_full_pipeline_order_is_fixed() -> None:
    schema = field(extra=NORMALIZE + 'case = "upper"\ncollapse_whitespace = true\ntrim = true\n')
    assert ok(schema, "  alice   example ") == "ALICE EXAMPLE"


def test_constraints_apply_after_trim() -> None:
    schema = field(extra="min_length = 5\n" + NORMALIZE + "trim = true\n")
    assert ok(schema, "  ALICE  ") == "ALICE"
    assert err(schema, "  AL   ") == (E.TOO_SHORT, "min_length")


def test_max_length_applies_after_case_mapping_that_grows_the_text() -> None:
    upper = NORMALIZE + 'case = "upper"\n'
    assert ok(field(extra="max_length = 2\n" + upper), "ß") == "SS"
    assert err(field(extra="max_length = 1\n" + upper), "ß") == (E.TOO_LONG, "max_length")


def test_lowercase_is_locale_independent() -> None:
    # Python's full Unicode mapping: dotted capital I becomes "i" + combining dot (2 code points).
    assert ok(field(extra=NORMALIZE + 'case = "lower"\n'), "İ") == "i̇"
    assert ok(field(extra=NORMALIZE + 'case = "lower"\n'), "ΣΑΣ") == "σας"


def test_nfc_is_always_applied_to_text() -> None:
    decomposed = "José"
    assert ok(field(), decomposed) == "José"
    assert ok(field("text_long"), decomposed) == "José"


def test_nfc_runs_after_case_and_before_length() -> None:
    upper = NORMALIZE + 'case = "upper"\n'
    assert ok(field(extra="max_length = 1\n" + upper), "é") == "É"


def test_no_accent_stripping_or_transliteration() -> None:
    schema = field(extra=NORMALIZE + 'trim = true\ncollapse_whitespace = true\ncase = "lower"\n')
    assert ok(schema, "Ángel Muñoz") == "ángel muñoz"


# integer


@pytest.mark.parametrize("value", [18, 0, -5])
def test_integer_valid(value: int) -> None:
    result = ok(field("integer"), value)
    assert result == value and type(result) is int


@pytest.mark.parametrize("value", ["18", 18.0, 1e2, True, False, "18 años", "", [18], "0x12"])
def test_integer_no_magic_conversion(value: object) -> None:
    assert err(field("integer"), value) == (E.INVALID_TYPE, None)


def test_integer_bounds_are_inclusive() -> None:
    schema = field("integer", "min = 0\nmax = 120\n")
    assert ok(schema, 0) == 0 and ok(schema, 120) == 120
    assert err(schema, -1) == (E.VALUE_TOO_SMALL, "min")
    assert err(schema, 121) == (E.VALUE_TOO_LARGE, "max")


def test_integer_int64_range() -> None:
    assert ok(field("integer"), 2**63 - 1) == 2**63 - 1
    assert ok(field("integer"), -(2**63)) == -(2**63)
    assert err(field("integer"), 2**63) == (E.VALUE_TOO_LARGE, "int64")
    assert err(field("integer"), -(2**63) - 1) == (E.VALUE_TOO_SMALL, "int64")


def test_zero_satisfies_required() -> None:
    assert ok(field("integer"), 0) == 0


# decimal


def dec(extra: str = "") -> ElementsSchema:
    return field("decimal", "decimal_places = 2\n" + extra)


def test_decimal_canonical_value_has_exactly_decimal_places() -> None:
    value = ok(dec(), "12.5")
    assert isinstance(value, Decimal)
    assert value == Decimal("12.50") and str(value) == "12.50"
    assert str(ok(dec(), "7")) == "7.00"
    assert str(ok(field("decimal", "decimal_places = 0\n"), "7")) == "7"


def test_decimal_never_rounds() -> None:
    assert err(dec(), "12.505") == (E.TOO_MANY_DECIMAL_PLACES, "decimal_places")
    # Trailing zeros still count: the input is not rewritten to fit.
    assert err(field("decimal", "decimal_places = 1\n"), "12.50") == (
        E.TOO_MANY_DECIMAL_PLACES,
        "decimal_places",
    )


@pytest.mark.parametrize("value", [12.5, 12, True, ["12.5"]])
def test_decimal_only_accepts_json_strings(value: object) -> None:
    assert err(dec(), value) == (E.INVALID_TYPE, None)


@pytest.mark.parametrize(
    "value",
    [
        "+1",
        "1e2",
        "1E2",
        "NaN",
        "Infinity",
        "-Infinity",
        ".5",
        "5.",
        " 1",
        "1 ",
        "01",
        "-01.5",
        "1,5",
        "1_000",
        "--1",
        "١٢",  # Arabic-Indic digits
        "１２",  # fullwidth digits
    ],
)
def test_decimal_grammar(value: str) -> None:
    assert err(dec(), value) == (E.INVALID_FORMAT, None)


def test_decimal_negative_zero_is_zero() -> None:
    value = ok(dec(), "-0.00")
    assert str(value) == "0.00" and not value.is_signed()  # type: ignore[union-attr]


def test_decimal_38_digit_limit() -> None:
    eighteen = field("decimal", "decimal_places = 18\n")
    assert str(ok(eighteen, "9" * 20 + "." + "9" * 18)) == "9" * 20 + "." + "9" * 18
    assert err(eighteen, "1" + "0" * 20) == (E.INVALID_FORMAT, None)
    # Padding counts: 37 integer digits + 2 places is 39 canonical digits.
    assert err(dec(), "1" * 37) == (E.INVALID_FORMAT, None)
    assert ok(dec(), "1" * 36) == Decimal("1" * 36 + ".00")


def test_decimal_does_not_depend_on_the_global_context() -> None:
    with localcontext() as ctx:
        ctx.prec = 3
        assert str(ok(dec(), "123456.78")) == "123456.78"


def test_decimal_bounds_are_inclusive() -> None:
    schema = dec('min = "0"\nmax = "99.99"\n')
    assert str(ok(schema, "0")) == "0.00" and str(ok(schema, "99.99")) == "99.99"
    assert err(schema, "-0.01") == (E.VALUE_TOO_SMALL, "min")
    assert err(schema, "100") == (E.VALUE_TOO_LARGE, "max")


# boolean


@pytest.mark.parametrize("value", [True, False])
def test_boolean_valid_and_false_satisfies_required(value: bool) -> None:
    assert ok(field("boolean"), value) is value


@pytest.mark.parametrize("value", ["true", "false", "yes", "no", "1", "0", 1, 0, "sí"])
def test_boolean_no_magic_conversion(value: object) -> None:
    assert err(field("boolean"), value) == (E.INVALID_TYPE, None)


# email


@pytest.mark.parametrize(
    "value",
    [
        "alice@example.com",
        "user@localhost",
        "a.b+tag@xn--bcher-kva.example",
        "o'brien@example.org",
        "x_y-z@sub-domain.example.co",
        "ALICE@Example.COM",
    ],
)
def test_email_valid_and_preserved(value: str) -> None:
    assert ok(field("email"), value) == value


@pytest.mark.parametrize(
    "value",
    [
        "alice",
        "@example.com",
        "alice@",
        ".alice@example.com",
        "alice.@example.com",
        "al..ice@example.com",
        "alice@-example.com",
        "alice@example-.com",
        "alice@exa_mple.com",
        "alice@example..com",
        "alice@example.com.",
        '"alice"@example.com',
        "alice@[127.0.0.1]",
        "alice(comment)@example.com",
        "álice@example.com",
        "alice@exämple.com",
        "alice @example.com",
        "alice@@example.com",
        " alice@example.com",
        "alice@" + "a" * 64 + ".com",
    ],
)
def test_email_invalid(value: str) -> None:
    assert err(field("email"), value) == (E.INVALID_FORMAT, None)


def test_email_length_limits() -> None:
    assert ok(field("email"), "a" * 64 + "@example.com")
    assert err(field("email"), "a" * 65 + "@example.com") == (E.INVALID_FORMAT, None)
    local = "a" * 64
    longest = local + "@" + ".".join(["b" * 63, "c" * 63, "d" * 61])
    assert len(longest) == 254 and ok(field("email"), longest) == longest
    assert err(field("email"), longest + "d") == (E.TOO_LONG, "max_length")


def test_email_declared_normalization() -> None:
    schema = field("email", NORMALIZE + 'trim = true\ncase = "lower"\n')
    assert ok(schema, "  ALICE@Example.COM ") == "alice@example.com"


# url


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        "http://example.com/path/to?q=1&r=a%20b#frag",
        "https://localhost:8080/",
        "http://127.0.0.1/",
        "http://[::1]:8080/x",
        "http://[2001:db8::1]",
        "https://xn--bcher-kva.example/%C3%A9",
        "HTTPS://Example.COM/A",
        "https://example.com/a:b@c;d=e,f!g$h'i(j)k*l+m~n",
        "https://example.com?x#y/z?",
    ],
)
def test_url_valid_and_preserved(value: str) -> None:
    assert ok(field("url"), value) == value


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/html,x",
        "mailto:alice@example.com",
        "//example.com",
        "/relative/path",
        "example.com",
        "https://user:pass@example.com",
        "https://user@example.com",
        "https://example.com/é",
        "https://exämple.com",
        "https://example.com/%zz",
        "https://example.com/%4",
        "https://exa mple.com",
        "https://example.com/a b",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:",
        "https://example.com:http",
        "https://[::1%25eth0]/",
        "https://[fe80::1%eth0]/",
        "https://[zz::1]/",
        "https://[::1]x/",
        "https://999.1.1.1/",
        "https://1.2.3/",
        "https:///path",
        "https://",
        "https://-example.com",
        "https://example.com#a#b",
        "https://example.com/\\",
        "https://example.com/<script>",
    ],
)
def test_url_invalid(value: str) -> None:
    assert err(field("url"), value) == (E.INVALID_FORMAT, None)


def test_url_length_limit() -> None:
    base = "https://example.com/"
    assert ok(field("url"), base + "a" * (2048 - len(base)))
    assert err(field("url"), base + "a" * (2049 - len(base))) == (E.TOO_LONG, "max_length")


# date


def test_date_valid() -> None:
    value = ok(field("date"), "2026-10-02")
    assert value == date(2026, 10, 2) and value.isoformat() == "2026-10-02"  # type: ignore[union-attr]
    assert ok(field("date"), "2024-02-29") == date(2024, 2, 29)


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-29",
        "2026-02-30",
        "2026-13-01",
        "0000-01-01",
        "02/10/2026",
        "2026-10-2",
        "2026-10-02T00:00:00Z",
        "20261002",
        "٢٠٢٦-١٠-٠٢",
        "2026-10-02 ",
    ],
)
def test_date_invalid(value: str) -> None:
    assert err(field("date"), value) == (E.INVALID_FORMAT, None)


def test_date_wrong_type() -> None:
    assert err(field("date"), 20261002) == (E.INVALID_TYPE, None)


def test_date_bounds() -> None:
    schema = field("date", "min = 2026-01-01\nmax = 2026-12-31\n")
    assert ok(schema, "2026-01-01") == date(2026, 1, 1)
    assert ok(schema, "2026-12-31") == date(2026, 12, 31)
    assert err(schema, "2025-12-31") == (E.VALUE_TOO_SMALL, "min")
    assert err(schema, "2027-01-01") == (E.VALUE_TOO_LARGE, "max")


# time


@pytest.mark.parametrize(("value", "expected"), [("18:30", "18:30:00"), ("18:30:15", "18:30:15")])
def test_time_canonical(value: str, expected: str) -> None:
    result = ok(field("time"), value)
    assert isinstance(result, time) and result.isoformat() == expected


@pytest.mark.parametrize(
    "value",
    ["24:00", "23:59:60", "18:30:00.5", "18:30Z", "18:30+01:00", "6:30", "18.30", "1830", "18:3"],
)
def test_time_invalid(value: str) -> None:
    assert err(field("time"), value) == (E.INVALID_FORMAT, None)


def test_time_bounds() -> None:
    schema = field("time", "min = 08:00:00\nmax = 18:00:00\n")
    assert ok(schema, "08:00") == time(8, 0)
    assert ok(schema, "18:00:00") == time(18, 0)
    assert err(schema, "07:59:59") == (E.VALUE_TOO_SMALL, "min")
    assert err(schema, "18:00:01") == (E.VALUE_TOO_LARGE, "max")


# datetime


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-02T18:30:00-06:00", datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),
        ("2026-10-02T18:30-06:00", datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),
        ("2026-10-03T00:30:00Z", datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),
        ("2026-10-03T05:45:00+05:15", datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),
        ("2026-10-03T00:30:00+00:00", datetime(2026, 10, 3, 0, 30, tzinfo=UTC)),
    ],
)
def test_datetime_is_canonical_utc(value: str, expected: datetime) -> None:
    result = ok(field("datetime"), value)
    assert result == expected
    assert isinstance(result, datetime) and result.tzinfo is UTC
    assert result.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-03T00:30:00Z"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-02T18:30:00",
        "2026-10-02T18:30",
        "2026-10-02t18:30:00Z",
        "2026-10-02T18:30:00z",
        "2026-10-02 18:30:00Z",
        "2026-10-02T18:30:00-00:00",
        "2026-10-02T18:30:00.5Z",
        "2026-10-02T18:30:00+24:00",
        "2026-10-02T18:30:00+05:60",
        "2026-10-02T18:30:00+0500",
        "2026-02-30T00:00:00Z",
        "2026-10-02T24:00:00Z",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:00-01:00",
        "2026-10-02",
    ],
)
def test_datetime_invalid(value: str) -> None:
    assert err(field("datetime"), value) == (E.INVALID_FORMAT, None)


def test_datetime_bounds_compare_instants() -> None:
    schema = field("datetime", "min = 2026-10-03T00:00:00Z\n")
    assert ok(schema, "2026-10-02T18:00:00-06:00") == datetime(2026, 10, 3, tzinfo=UTC)
    assert err(schema, "2026-10-02T17:59:59-06:00") == (E.VALUE_TOO_SMALL, "min")


# select


def test_select_stores_the_value() -> None:
    assert ok(field("select", OPTIONS), "am") == "am"


@pytest.mark.parametrize("value", ["Matutina", "AM", " am", "am ", "x", "0"])
def test_select_requires_an_exact_value(value: str) -> None:
    assert err(field("select", OPTIONS), value) == (E.INVALID_OPTION, None)


@pytest.mark.parametrize("value", [1, ["am"], True, {"value": "am"}])
def test_select_wrong_type(value: object) -> None:
    assert err(field("select", OPTIONS), value) == (E.INVALID_TYPE, None)


# multi_select


def test_multi_select_canonical_order_is_declaration_order() -> None:
    assert ok(field("multi_select", OPTIONS), ["night", "am"]) == ("am", "night")
    assert ok(field("multi_select", OPTIONS), ["am", "night"]) == ("am", "night")


def test_multi_select_empty_list_is_no_answer() -> None:
    assert err(field("multi_select", OPTIONS), []) == (E.FIELD_REQUIRED, "required")
    assert omitted(field("multi_select", OPTIONS, required=False), [])
    # min_selected does not turn an optional element into a required one.
    optional = field("multi_select", "min_selected = 2\n" + OPTIONS, required=False)
    assert omitted(optional, [])


def test_multi_select_duplicates_are_rejected_not_merged() -> None:
    assert err(field("multi_select", OPTIONS), ["am", "am"]) == (E.DUPLICATE_SELECTION, None)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (["x"], E.INVALID_OPTION),
        (["Matutina"], E.INVALID_OPTION),
        ([""], E.INVALID_OPTION),
        ([1], E.INVALID_TYPE),
        ([None], E.INVALID_TYPE),
        ("am", E.INVALID_TYPE),
        (("am",), E.INVALID_TYPE),
        ({"am": True}, E.INVALID_TYPE),
    ],
)
def test_multi_select_invalid(value: object, code: AnswerErrorCode) -> None:
    assert err(field("multi_select", OPTIONS), value) == (code, None)


def test_multi_select_bounds() -> None:
    schema = field("multi_select", "min_selected = 2\nmax_selected = 2\n" + OPTIONS)
    assert ok(schema, ["pm", "am"]) == ("am", "pm")
    assert err(schema, ["am"]) == (E.TOO_FEW_SELECTED, "min_selected")
    assert err(schema, ["am", "pm", "night"]) == (E.TOO_MANY_SELECTED, "max_selected")
