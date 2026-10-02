"""Local validation of an answers payload against an ElementsSchema.

Pure and in-memory: no persistence, no database, no Resources, no Rules. User errors are
returned as data, never raised. Error messages are fixed per code and never echo the input.
The pipeline and the codes are the contract in ELEMENTS_SCHEMA.md.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Protocol, assert_never

from app.forms.elements import (
    INT64_MAX,
    INT64_MIN,
    BooleanElement,
    DateElement,
    DateTimeElement,
    DecimalElement,
    Element,
    ElementsSchema,
    EmailElement,
    IntegerElement,
    MultiSelectElement,
    Normalization,
    SelectElement,
    TextElement,
    TimeElement,
    UrlElement,
    is_valid_element_id,
    parse_decimal,
)

MAX_ERRORS = 20
EMAIL_MAX_LENGTH = 254
EMAIL_LOCAL_MAX_LENGTH = 64
URL_MAX_LENGTH = 2048


class AnswerErrorCode(StrEnum):
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    FIELD_REQUIRED = "FIELD_REQUIRED"
    INVALID_TYPE = "INVALID_TYPE"
    INVALID_CHARACTERS = "INVALID_CHARACTERS"
    INVALID_FORMAT = "INVALID_FORMAT"
    VALUE_TOO_SMALL = "VALUE_TOO_SMALL"
    VALUE_TOO_LARGE = "VALUE_TOO_LARGE"
    TOO_SHORT = "TOO_SHORT"
    TOO_LONG = "TOO_LONG"
    TOO_MANY_DECIMAL_PLACES = "TOO_MANY_DECIMAL_PLACES"
    INVALID_OPTION = "INVALID_OPTION"
    DUPLICATE_SELECTION = "DUPLICATE_SELECTION"
    TOO_FEW_SELECTED = "TOO_FEW_SELECTED"
    TOO_MANY_SELECTED = "TOO_MANY_SELECTED"


_MESSAGES: Mapping[AnswerErrorCode, str] = MappingProxyType(
    {
        AnswerErrorCode.INVALID_PAYLOAD: "La respuesta debe ser un objeto JSON.",
        AnswerErrorCode.UNKNOWN_FIELD: "El campo no existe en este formulario.",
        AnswerErrorCode.FIELD_REQUIRED: "El campo es obligatorio.",
        AnswerErrorCode.INVALID_TYPE: "El valor no tiene el tipo esperado.",
        AnswerErrorCode.INVALID_CHARACTERS: "El texto contiene caracteres no permitidos.",
        AnswerErrorCode.INVALID_FORMAT: "El valor no tiene un formato válido.",
        AnswerErrorCode.VALUE_TOO_SMALL: "El valor es menor que el mínimo permitido.",
        AnswerErrorCode.VALUE_TOO_LARGE: "El valor es mayor que el máximo permitido.",
        AnswerErrorCode.TOO_SHORT: "El texto es más corto que el mínimo permitido.",
        AnswerErrorCode.TOO_LONG: "El valor supera la longitud máxima permitida.",
        AnswerErrorCode.TOO_MANY_DECIMAL_PLACES: "El valor tiene más decimales de los permitidos.",
        AnswerErrorCode.INVALID_OPTION: "El valor no es una de las opciones permitidas.",
        AnswerErrorCode.DUPLICATE_SELECTION: "Una opción está seleccionada más de una vez.",
        AnswerErrorCode.TOO_FEW_SELECTED: "Hay menos opciones seleccionadas de las requeridas.",
        AnswerErrorCode.TOO_MANY_SELECTED: "Hay más opciones seleccionadas de las permitidas.",
    }
)

CanonicalValue = str | int | bool | Decimal | date | time | datetime | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FieldError:
    # None when the error is not about a declared element (payload shape, unsafe unknown key).
    element_id: str | None
    code: AnswerErrorCode
    message: str
    constraint: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    # Empty whenever errors is not: partial canonical values are never returned.
    values: Mapping[str, CanonicalValue]
    errors: tuple[FieldError, ...]


@dataclass(frozen=True, slots=True)
class _Invalid:
    code: AnswerErrorCode
    constraint: str | None = None


class _NoAnswer(Enum):
    """Absent key, blank string or empty list: the element was not answered."""

    NO_ANSWER = "NO_ANSWER"


_NO_ANSWER = _NoAnswer.NO_ANSWER
_Outcome = CanonicalValue | _Invalid | _NoAnswer


def _error(element_id: str | None, code: AnswerErrorCode, constraint: str | None) -> FieldError:
    return FieldError(element_id, code, _MESSAGES[code], constraint)


def validate_answers(schema: ElementsSchema, payload: object) -> ValidationResult:
    if not isinstance(payload, Mapping):
        error = _error(None, AnswerErrorCode.INVALID_PAYLOAD, None)
        return ValidationResult(False, MappingProxyType({}), (error,))

    errors: list[FieldError] = []
    values: dict[str, CanonicalValue] = {}
    for element in schema.elements:
        if len(errors) >= MAX_ERRORS:
            break
        outcome = _validate(element, payload[element.id]) if element.id in payload else _NO_ANSWER
        if isinstance(outcome, _Invalid):
            errors.append(_error(element.id, outcome.code, outcome.constraint))
        elif outcome is _NO_ANSWER:
            if element.required:
                errors.append(_error(element.id, AnswerErrorCode.FIELD_REQUIRED, "required"))
        else:
            values[element.id] = outcome

    unknown = [key for key in payload if not (isinstance(key, str) and key in schema.by_id)]
    for key in sorted(unknown, key=lambda k: (0, k) if isinstance(k, str) else (1, "")):
        if len(errors) >= MAX_ERRORS:
            break
        # The key is client input: it is only echoed when it is a harmless identifier.
        shown = key if is_valid_element_id(key) else None
        errors.append(_error(shown, AnswerErrorCode.UNKNOWN_FIELD, None))

    if errors:
        return ValidationResult(False, MappingProxyType({}), tuple(errors))
    return ValidationResult(True, MappingProxyType(values), ())


def _validate(element: Element, raw: object) -> _Outcome:
    match element:
        case TextElement():
            return _text(element, raw)
        case IntegerElement():
            return _integer(element, raw)
        case DecimalElement():
            return _decimal(element, raw)
        case BooleanElement():
            return raw if type(raw) is bool else _Invalid(AnswerErrorCode.INVALID_TYPE)
        case EmailElement():
            return _email(element, raw)
        case UrlElement():
            return _url(raw)
        case DateElement():
            return _date(element, raw)
        case TimeElement():
            return _time(element, raw)
        case DateTimeElement():
            return _datetime(element, raw)
        case SelectElement():
            return _select(element, raw)
        case MultiSelectElement():
            return _multi_select(element, raw)
        case _:
            assert_never(element)


def _string(raw: object) -> str | _Invalid | _NoAnswer:
    """The first two steps for every string-typed element: real JSON string, then blankness.
    Blank is decided on the raw string, so "\\t" is "not answered" even where TAB is invalid."""
    if type(raw) is not str:
        return _Invalid(AnswerErrorCode.INVALID_TYPE)
    if not raw.strip():
        return _NO_ANSWER
    return raw


class _Comparable(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...
    def __gt__(self, other: Any, /) -> bool: ...


def _range[C: _Comparable](value: C, low: C | None, high: C | None) -> _Invalid | None:
    if low is not None and value < low:
        return _Invalid(AnswerErrorCode.VALUE_TOO_SMALL, "min")
    if high is not None and value > high:
        return _Invalid(AnswerErrorCode.VALUE_TOO_LARGE, "max")
    return None


# C0 (TAB, LF and CR included), DEL, C1 and lone surrogates, which cannot be stored as UTF-8.
_TEXT_FORBIDDEN_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_TEXT_LONG_FORBIDDEN_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")
# \s matches exactly the characters str.isspace() and str.strip() treat as whitespace.
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _normalize(value: str, rules: Normalization) -> str:
    if rules.trim:
        value = value.strip()
    if rules.collapse_whitespace:
        value = _WHITESPACE_RUN_RE.sub(" ", value)
    if rules.case == "lower":
        value = value.lower()
    elif rules.case == "upper":
        value = value.upper()
    return value


def _text(element: TextElement, raw: object) -> _Outcome:
    value = _string(raw)
    if not isinstance(value, str):
        return value
    forbidden = _TEXT_FORBIDDEN_RE
    if element.type == "text_long":
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        forbidden = _TEXT_LONG_FORBIDDEN_RE
    if forbidden.search(value):
        return _Invalid(AnswerErrorCode.INVALID_CHARACTERS)
    value = unicodedata.normalize("NFC", _normalize(value, element.normalize))
    if element.min_length is not None and len(value) < element.min_length:
        return _Invalid(AnswerErrorCode.TOO_SHORT, "min_length")
    if len(value) > element.max_length:
        return _Invalid(AnswerErrorCode.TOO_LONG, "max_length")
    return value


def _integer(element: IntegerElement, raw: object) -> _Outcome:
    # type() rather than isinstance(): bool is an int subclass and must never pass as one.
    if type(raw) is not int:
        return _Invalid(AnswerErrorCode.INVALID_TYPE)
    if raw < INT64_MIN:
        return _Invalid(AnswerErrorCode.VALUE_TOO_SMALL, "int64")
    if raw > INT64_MAX:
        return _Invalid(AnswerErrorCode.VALUE_TOO_LARGE, "int64")
    return _range(raw, element.min, element.max) or raw


def _decimal(element: DecimalElement, raw: object) -> _Outcome:
    text = _string(raw)
    if not isinstance(text, str):
        return text
    value = parse_decimal(text, element.decimal_places)
    if value == "TOO_MANY_DECIMAL_PLACES":
        return _Invalid(AnswerErrorCode.TOO_MANY_DECIMAL_PLACES, "decimal_places")
    if not isinstance(value, Decimal):
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return _range(value, element.min, element.max) or value


_PRINTABLE_ASCII_RE = re.compile(r"[\x20-\x7e]*\Z")
_LDH_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_LDH_LABEL_RE = re.compile(_LDH_LABEL + r"\Z")
_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_EMAIL_RE = re.compile(rf"{_ATEXT}(?:\.{_ATEXT})*@{_LDH_LABEL}(?:\.{_LDH_LABEL})*\Z")


def _email(element: EmailElement, raw: object) -> _Outcome:
    value = _string(raw)
    if not isinstance(value, str):
        return value
    if not _PRINTABLE_ASCII_RE.match(value):
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    value = _normalize(value, element.normalize)
    if len(value) > EMAIL_MAX_LENGTH:
        return _Invalid(AnswerErrorCode.TOO_LONG, "max_length")
    if _EMAIL_RE.match(value) is None or len(value.partition("@")[0]) > EMAIL_LOCAL_MAX_LENGTH:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return value


_URL_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)(.*)\Z")
_PCHAR = r"(?:[A-Za-z0-9._~!$&'()*+,;=:@-]|%[0-9A-Fa-f]{2})"
_URL_TAIL_RE = re.compile(
    rf"(?:/(?:{_PCHAR}|/)*)?(?:\?(?:{_PCHAR}|[/?])*)?(?:#(?:{_PCHAR}|[/?])*)?\Z"
)
_PORT_RE = re.compile(r"[0-9]{1,5}\Z")
_IPV6_CHARS_RE = re.compile(r"[0-9A-Fa-f:.]+\Z")


def _valid_host(host: str) -> bool:
    if host.startswith("["):
        inner = host[1:-1]
        # Zone IDs ("%eth0") are rejected: the bracketed text must be a bare IPv6 address.
        if not host.endswith("]") or not _IPV6_CHARS_RE.match(inner):
            return False
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return False
        return True
    labels = host.split(".")
    if not all(_LDH_LABEL_RE.match(label) for label in labels):
        return False
    if all(label.isdigit() for label in labels):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            return False
    return True


def _url(raw: object) -> _Outcome:
    value = _string(raw)
    if not isinstance(value, str):
        return value
    if len(value) > URL_MAX_LENGTH:
        return _Invalid(AnswerErrorCode.TOO_LONG, "max_length")
    match = _URL_RE.match(value) if _PRINTABLE_ASCII_RE.match(value) else None
    if match is None:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    scheme, authority, tail = match.groups()
    if scheme.lower() not in ("http", "https") or "@" in authority:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    if authority.startswith("["):
        host, _, after = authority.partition("]")
        host += "]"
        port_sep, port = after[:1], after[1:]
        if after and port_sep != ":":
            return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    else:
        host, port_sep, port = authority.partition(":")
    if port_sep and not (_PORT_RE.match(port) and 1 <= int(port) <= 65535):
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    if not _valid_host(host) or _URL_TAIL_RE.match(tail) is None:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return value


_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_TIME_RE = re.compile(r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?\Z")
_DATETIME_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?"
    r"(?:(Z)|([+-])([0-9]{2}):([0-9]{2}))\Z"
)


def _date(element: DateElement, raw: object) -> _Outcome:
    text = _string(raw)
    if not isinstance(text, str):
        return text
    match = _DATE_RE.match(text)
    try:
        value = date(*map(int, match.groups())) if match else None
    except ValueError:
        value = None
    if value is None:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return _range(value, element.min, element.max) or value


def _time(element: TimeElement, raw: object) -> _Outcome:
    text = _string(raw)
    if not isinstance(text, str):
        return text
    match = _TIME_RE.match(text)
    value: time | None = None
    if match:
        hour, minute, second = match.groups()
        try:
            # An omitted seconds group means :00.
            value = time(int(hour), int(minute), int(second or 0))
        except ValueError:
            value = None
    if value is None:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return _range(value, element.min, element.max) or value


def _parse_datetime(text: str) -> datetime | None:
    match = _DATETIME_RE.match(text)
    if match is None:
        return None
    year, month, day, hour, minute, second, zulu, sign, offset_hours, offset_minutes = (
        match.groups()
    )
    if zulu:
        tz = UTC
    else:
        # RFC 3339 "-00:00" means "offset unknown", which is not an offset.
        if sign == "-" and offset_hours == "00" and offset_minutes == "00":
            return None
        if int(offset_hours) > 23 or int(offset_minutes) > 59:
            return None
        delta = timedelta(hours=int(offset_hours), minutes=int(offset_minutes))
        tz = timezone(-delta if sign == "-" else delta)
    try:
        local = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=tz
        )
        return local.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _datetime(element: DateTimeElement, raw: object) -> _Outcome:
    text = _string(raw)
    if not isinstance(text, str):
        return text
    value = _parse_datetime(text)
    if value is None:
        return _Invalid(AnswerErrorCode.INVALID_FORMAT)
    return _range(value, element.min, element.max) or value


def _select(element: SelectElement, raw: object) -> _Outcome:
    value = _string(raw)
    if not isinstance(value, str):
        return value
    if all(option.value != value for option in element.options):
        return _Invalid(AnswerErrorCode.INVALID_OPTION)
    return value


def _multi_select(element: MultiSelectElement, raw: object) -> _Outcome:
    if type(raw) is not list:
        return _Invalid(AnswerErrorCode.INVALID_TYPE)
    if not raw:
        return _NO_ANSWER
    position = {option.value: index for index, option in enumerate(element.options)}
    chosen: set[str] = set()
    for item in raw:
        if type(item) is not str:
            return _Invalid(AnswerErrorCode.INVALID_TYPE)
        if item not in position:
            return _Invalid(AnswerErrorCode.INVALID_OPTION)
        if item in chosen:
            return _Invalid(AnswerErrorCode.DUPLICATE_SELECTION)
        chosen.add(item)
    if element.min_selected is not None and len(chosen) < element.min_selected:
        return _Invalid(AnswerErrorCode.TOO_FEW_SELECTED, "min_selected")
    if element.max_selected is not None and len(chosen) > element.max_selected:
        return _Invalid(AnswerErrorCode.TOO_MANY_SELECTED, "max_selected")
    # Client order carries no meaning; the canonical order is the declaration order.
    return tuple(sorted(chosen, key=position.__getitem__))
