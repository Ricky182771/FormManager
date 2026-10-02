"""elements.toml, schema_version 1: typed element definitions and their explicit parser.

The contract is ELEMENTS_SCHEMA.md. The parser is hand-written on purpose: every property is
checked against a per-type allowlist, so a diagnostic can tell an unknown property apart from a
known one that does not apply to the element's type.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Context, Decimal, Inexact, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal, TypedDict, TypeVar

from app.forms.diagnostics import DiagnosticCode, safe_name

ELEMENT_ID_MAX_LENGTH = 64
ELEMENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*\Z")
OPTION_VALUE_MAX_LENGTH = 64
OPTION_VALUE_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*\Z")

MAX_ELEMENTS = 200
MAX_OPTIONS = 200
LABEL_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000
TEXT_MAX_LENGTH = 1000
TEXT_LONG_MAX_LENGTH = 10_000
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
DECIMAL_PLACES_MAX = 18
DECIMAL_MAX_DIGITS = 38

# Part of the v1 direction but not usable yet: they get their own diagnostic, not "unknown".
DEFERRED_TYPES = frozenset({"resource_select", "resource_multi_select"})
# Deferred for safety: Python's re has no protection against catastrophic backtracking.
DEFERRED_PROPERTIES = frozenset({"pattern"})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CONTROL_EXCEPT_LF_TAB_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(?:\.([0-9]+))?\Z")
# Local context: never depend on the process-wide default precision (28). Inexact is trapped,
# so a quantize that would round raises instead.
_DECIMAL_CONTEXT = Context(prec=DECIMAL_MAX_DIGITS, traps=[InvalidOperation, Inexact])

Case = Literal["lower", "upper"]


@dataclass(frozen=True, slots=True)
class Normalization:
    """Applied in a fixed order: trim, collapse_whitespace, case (then NFC for text types)."""

    trim: bool = False
    collapse_whitespace: bool = False
    case: Case | None = None


@dataclass(frozen=True, slots=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ElementBase:
    id: str
    label: str
    required: bool
    description: str | None


@dataclass(frozen=True, slots=True)
class TextElement(ElementBase):
    type: Literal["text", "text_long"]
    min_length: int | None
    # Always set: the declared max_length or the type's hard maximum.
    max_length: int
    normalize: Normalization


@dataclass(frozen=True, slots=True)
class IntegerElement(ElementBase):
    min: int | None
    max: int | None


@dataclass(frozen=True, slots=True)
class DecimalElement(ElementBase):
    decimal_places: int
    min: Decimal | None
    max: Decimal | None


@dataclass(frozen=True, slots=True)
class BooleanElement(ElementBase):
    pass


@dataclass(frozen=True, slots=True)
class EmailElement(ElementBase):
    normalize: Normalization


@dataclass(frozen=True, slots=True)
class UrlElement(ElementBase):
    pass


@dataclass(frozen=True, slots=True)
class DateElement(ElementBase):
    min: date | None
    max: date | None


@dataclass(frozen=True, slots=True)
class TimeElement(ElementBase):
    min: time | None
    max: time | None


@dataclass(frozen=True, slots=True)
class DateTimeElement(ElementBase):
    # Stored in UTC.
    min: datetime | None
    max: datetime | None


@dataclass(frozen=True, slots=True)
class SelectElement(ElementBase):
    options: tuple[Option, ...]


@dataclass(frozen=True, slots=True)
class MultiSelectElement(ElementBase):
    options: tuple[Option, ...]
    min_selected: int | None
    max_selected: int | None


Element = (
    TextElement
    | IntegerElement
    | DecimalElement
    | BooleanElement
    | EmailElement
    | UrlElement
    | DateElement
    | TimeElement
    | DateTimeElement
    | SelectElement
    | MultiSelectElement
)


@dataclass(frozen=True, slots=True)
class ElementsSchema:
    elements: tuple[Element, ...] = ()
    by_id: Mapping[str, Element] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def build(cls, elements: tuple[Element, ...]) -> ElementsSchema:
        return cls(elements, MappingProxyType({e.id: e for e in elements}))


def is_valid_element_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= ELEMENT_ID_MAX_LENGTH
        and ELEMENT_ID_RE.match(value) is not None
    )


DecimalProblem = Literal["INVALID_FORMAT", "TOO_MANY_DECIMAL_PLACES"]


def parse_decimal(text: str, places: int) -> Decimal | DecimalProblem:
    """Exact fixed-point parsing shared by the schema (min/max) and answers. Never rounds.

    The canonical value has exactly `places` fractional digits; its digit count is the integer
    part's digits plus `places` and may not exceed DECIMAL_MAX_DIGITS. Negative zero becomes 0.
    """
    match = DECIMAL_RE.match(text)
    if match is None:
        return "INVALID_FORMAT"
    integer_part, fraction = match.group(1), match.group(2) or ""
    if len(fraction) > places:
        return "TOO_MANY_DECIMAL_PLACES"
    if len(integer_part) + places > DECIMAL_MAX_DIGITS:
        return "INVALID_FORMAT"
    value = Decimal(text).quantize(Decimal(1).scaleb(-places), context=_DECIMAL_CONTEXT)
    return value.copy_abs() if value.is_zero() else value


_TEXT_PROPERTIES = frozenset({"min_length", "max_length", "normalize"})
_RANGE_PROPERTIES = frozenset({"min", "max"})
_TYPE_PROPERTIES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "text": _TEXT_PROPERTIES,
        "text_long": _TEXT_PROPERTIES,
        "integer": _RANGE_PROPERTIES,
        "decimal": _RANGE_PROPERTIES | {"decimal_places"},
        "boolean": frozenset(),
        "email": frozenset({"normalize"}),
        "url": frozenset(),
        "date": _RANGE_PROPERTIES,
        "time": _RANGE_PROPERTIES,
        "datetime": _RANGE_PROPERTIES,
        "select": frozenset({"options"}),
        "multi_select": frozenset({"options", "min_selected", "max_selected"}),
    }
)
_COMMON_PROPERTIES = frozenset({"id", "type", "label", "required", "description"})
_KNOWN_PROPERTIES = frozenset().union(*_TYPE_PROPERTIES.values())
_NORMALIZE_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "text": frozenset({"trim", "collapse_whitespace", "case"}),
        # Collapsing would destroy line breaks.
        "text_long": frozenset({"trim", "case"}),
        "email": frozenset({"trim", "case"}),
    }
)
_NORMALIZE_CASES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"text": ("lower", "upper"), "text_long": ("lower", "upper"), "email": ("lower",)}
)

Problem = tuple[DiagnosticCode, str]
_T = TypeVar("_T")


class _Common(TypedDict):
    id: str
    label: str
    required: bool
    description: str | None


_PLACEHOLDER = _Common(id="", label="", required=False, description=None)


def parse_elements(document: Mapping[str, Any]) -> tuple[ElementsSchema | None, list[Problem]]:
    """Validate a parsed elements.toml. schema_version is checked by the loader beforehand."""
    problems: list[Problem] = []
    for key in sorted(set(document) - {"schema_version", "element"}):
        problems.append(
            (DiagnosticCode.INVALID_ELEMENTS_SCHEMA, f"Propiedad desconocida {safe_name(key)}.")
        )
    raw = document.get("element", [])
    if not isinstance(raw, list) or not all(isinstance(table, dict) for table in raw):
        problems.append(
            (DiagnosticCode.INVALID_ELEMENTS_SCHEMA, "element debe ser una lista de [[element]].")
        )
        return None, problems
    if len(raw) > MAX_ELEMENTS:
        problems.append(
            (DiagnosticCode.TOO_MANY_ELEMENTS, f"Se admiten como máximo {MAX_ELEMENTS} elementos.")
        )
        return None, problems

    elements: list[Element] = []
    seen: set[str] = set()
    for index, table in enumerate(raw, start=1):
        element_id = table.get("id")
        if is_valid_element_id(element_id):
            if element_id in seen:
                problems.append(
                    (
                        DiagnosticCode.DUPLICATE_ELEMENT_ID,
                        f"Elemento {index}: el id {element_id} ya está declarado.",
                    )
                )
            seen.add(element_id)
        element = _ElementParser(index, table, problems).parse()
        if element is not None:
            elements.append(element)
    if problems:
        return None, problems
    return ElementsSchema.build(tuple(elements)), []


def _checked_label(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value.strip()
        and len(value) <= LABEL_MAX_LENGTH
        and _CONTROL_RE.search(value) is None
    ):
        return value
    return None


class _ElementParser:
    """Parses one [[element]] table, appending every problem found to the shared list."""

    def __init__(self, index: int, table: dict[str, Any], problems: list[Problem]) -> None:
        self._table = table
        self._problems = problems
        raw_id = table.get("id")
        self._ref = f"Elemento {index}"
        if is_valid_element_id(raw_id):
            self._ref += f" ({raw_id})"
        self._ok = True

    def _problem(self, code: DiagnosticCode, message: str) -> None:
        self._problems.append((code, f"{self._ref}: {message}"))
        self._ok = False

    def parse(self) -> Element | None:
        common = self._common()
        kind = self._type()
        if kind is None:
            return None
        self._check_property_names(kind)
        # With invalid common properties the type-specific checks still run, so every problem
        # is reported at once; the placeholder result is discarded because _ok is already False.
        element = self._build(kind, common or _PLACEHOLDER)
        return element if self._ok else None

    def _common(self) -> _Common | None:
        table = self._table
        element_id = table.get("id")
        if "id" not in table:
            self._problem(DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad id.")
        elif not is_valid_element_id(element_id):
            self._problem(
                DiagnosticCode.INVALID_ELEMENT_ID,
                "id inválido (a-z, 0-9, _ y -; empieza por letra; máximo 64).",
            )
        label = table.get("label")
        if "label" not in table:
            self._problem(DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad label.")
        elif _checked_label(label) is None:
            self._problem(DiagnosticCode.INVALID_ELEMENT_PROPERTY, "label inválido.")
        required = table.get("required")
        if "required" not in table:
            self._problem(DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad required.")
        elif type(required) is not bool:
            self._problem(
                DiagnosticCode.INVALID_ELEMENT_PROPERTY, "required debe ser true o false."
            )
        description = table.get("description")
        if description is not None and not (
            isinstance(description, str)
            and description.strip()
            and len(description) <= DESCRIPTION_MAX_LENGTH
            and _CONTROL_EXCEPT_LF_TAB_RE.search(description) is None
        ):
            self._problem(DiagnosticCode.INVALID_ELEMENT_PROPERTY, "description inválida.")
        if not (
            isinstance(element_id, str)
            and isinstance(label, str)
            and isinstance(required, bool)
            and (description is None or isinstance(description, str))
        ):
            return None
        return _Common(id=element_id, label=label, required=required, description=description)

    def _type(self) -> str | None:
        if "type" not in self._table:
            self._problem(DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad type.")
            return None
        kind = self._table["type"]
        if isinstance(kind, str) and kind in DEFERRED_TYPES:
            self._problem(
                DiagnosticCode.UNSUPPORTED_ELEMENT_TYPE,
                f"el tipo {kind} requiere el subsistema Resources, que todavía no existe.",
            )
            return None
        if not isinstance(kind, str) or kind not in _TYPE_PROPERTIES:
            shown = safe_name(kind) if isinstance(kind, str) else "no textual"
            self._problem(DiagnosticCode.UNKNOWN_ELEMENT_TYPE, f"tipo desconocido {shown}.")
            return None
        return kind

    def _check_property_names(self, kind: str) -> None:
        allowed = _COMMON_PROPERTIES | _TYPE_PROPERTIES[kind]
        for key in sorted(set(self._table) - allowed):
            name = safe_name(key)
            if key in DEFERRED_PROPERTIES:
                self._problem(
                    DiagnosticCode.UNSUPPORTED_ELEMENT_PROPERTY,
                    f"{name} está diferido y no forma parte de Elements v1.",
                )
            elif key == "normalize":
                self._problem(
                    DiagnosticCode.INVALID_NORMALIZATION, f"normalize no aplica a {kind}."
                )
            elif key == "options":
                self._problem(DiagnosticCode.INVALID_OPTIONS, f"options no aplica a {kind}.")
            elif key in _KNOWN_PROPERTIES:
                self._problem(DiagnosticCode.INVALID_CONSTRAINT, f"{name} no aplica a {kind}.")
            else:
                self._problem(
                    DiagnosticCode.UNKNOWN_ELEMENT_PROPERTY, f"propiedad desconocida {name}."
                )

    def _build(self, kind: str, common: _Common) -> Element | None:
        match kind:
            case "text" | "text_long":
                return self._text(kind, common)
            case "integer":
                minimum = self._bound("min", _is_int64, lambda v: v)
                maximum = self._bound("max", _is_int64, lambda v: v)
                self._check_order(minimum, maximum, "min", "max")
                return IntegerElement(**common, min=minimum, max=maximum)
            case "decimal":
                return self._decimal(common)
            case "boolean":
                return BooleanElement(**common)
            case "email":
                return EmailElement(**common, normalize=self._normalize("email"))
            case "url":
                return UrlElement(**common)
            case "date":
                min_date = self._bound("min", lambda v: type(v) is date, lambda v: v)
                max_date = self._bound("max", lambda v: type(v) is date, lambda v: v)
                self._check_order(min_date, max_date, "min", "max")
                return DateElement(**common, min=min_date, max=max_date)
            case "time":
                min_time = self._bound("min", _is_local_time, lambda v: v)
                max_time = self._bound("max", _is_local_time, lambda v: v)
                self._check_order(min_time, max_time, "min", "max")
                return TimeElement(**common, min=min_time, max=max_time)
            case "datetime":
                min_dt = self._bound("min", _is_offset_datetime, lambda v: v.astimezone(UTC))
                max_dt = self._bound("max", _is_offset_datetime, lambda v: v.astimezone(UTC))
                self._check_order(min_dt, max_dt, "min", "max")
                return DateTimeElement(**common, min=min_dt, max=max_dt)
            case "select":
                return SelectElement(**common, options=self._options())
            case _:
                options = self._options()
                count = max(len(options), 1)
                min_selected = self._int_constraint("min_selected", 1, count)
                max_selected = self._int_constraint("max_selected", 1, count)
                self._check_order(min_selected, max_selected, "min_selected", "max_selected")
                return MultiSelectElement(
                    **common,
                    options=options,
                    min_selected=min_selected,
                    max_selected=max_selected,
                )

    def _text(self, kind: Literal["text", "text_long"], common: _Common) -> TextElement:
        hard_max = TEXT_MAX_LENGTH if kind == "text" else TEXT_LONG_MAX_LENGTH
        min_length = self._int_constraint("min_length", 1, hard_max)
        max_length = self._int_constraint("max_length", 1, hard_max)
        self._check_order(min_length, max_length, "min_length", "max_length")
        return TextElement(
            **common,
            type=kind,
            min_length=min_length,
            max_length=max_length if max_length is not None else hard_max,
            normalize=self._normalize(kind),
        )

    def _decimal(self, common: _Common) -> DecimalElement | None:
        if "decimal_places" not in self._table:
            self._problem(
                DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad decimal_places."
            )
            return None
        places = self._int_constraint("decimal_places", 0, DECIMAL_PLACES_MAX)
        if places is None:
            return None
        bounds: dict[str, Decimal | None] = {}
        for name in ("min", "max"):
            raw = self._table.get(name)
            parsed = parse_decimal(raw, places) if isinstance(raw, str) else None
            bounds[name] = parsed if isinstance(parsed, Decimal) else None
            if raw is not None and bounds[name] is None:
                self._problem(
                    DiagnosticCode.INVALID_CONSTRAINT,
                    f"{name} debe ser un decimal en texto con como máximo {places} decimales.",
                )
        self._check_order(bounds["min"], bounds["max"], "min", "max")
        return DecimalElement(**common, decimal_places=places, min=bounds["min"], max=bounds["max"])

    def _int_constraint(self, name: str, low: int, high: int) -> int | None:
        value = self._table.get(name)
        if value is None:
            return None
        if type(value) is not int or not low <= value <= high:
            self._problem(
                DiagnosticCode.INVALID_CONSTRAINT,
                f"{name} debe ser un entero entre {low} y {high}.",
            )
            return None
        return value

    def _bound(
        self, name: str, accepts: Callable[[Any], bool], convert: Callable[[Any], _T]
    ) -> _T | None:
        value = self._table.get(name)
        if value is None:
            return None
        if not accepts(value):
            self._problem(DiagnosticCode.INVALID_CONSTRAINT, f"{name} no tiene el tipo esperado.")
            return None
        return convert(value)

    def _check_order(self, low: Any, high: Any, low_name: str, high_name: str) -> None:
        if low is not None and high is not None and low > high:
            self._problem(
                DiagnosticCode.INVALID_CONSTRAINT, f"{low_name} no puede ser mayor que {high_name}."
            )

    def _normalize(self, kind: str) -> Normalization:
        raw = self._table.get("normalize")
        if raw is None:
            return Normalization()
        if not isinstance(raw, dict):
            self._problem(DiagnosticCode.INVALID_NORMALIZATION, "normalize debe ser una tabla.")
            return Normalization()
        for key in sorted(set(raw) - _NORMALIZE_KEYS[kind]):
            self._problem(
                DiagnosticCode.INVALID_NORMALIZATION,
                f"normalize.{safe_name(key)} no está permitido para {kind}.",
            )
        flags: dict[str, bool] = {}
        for key in ("trim", "collapse_whitespace"):
            value = raw.get(key, False)
            if type(value) is not bool:
                self._problem(
                    DiagnosticCode.INVALID_NORMALIZATION, f"normalize.{key} debe ser true o false."
                )
                value = False
            flags[key] = value
        case = raw.get("case")
        if case is not None and case not in _NORMALIZE_CASES[kind]:
            allowed = " o ".join(_NORMALIZE_CASES[kind])
            self._problem(
                DiagnosticCode.INVALID_NORMALIZATION, f"normalize.case debe ser {allowed}."
            )
            case = None
        return Normalization(
            trim=flags["trim"], collapse_whitespace=flags["collapse_whitespace"], case=case
        )

    def _options(self) -> tuple[Option, ...]:
        if "options" not in self._table:
            self._problem(DiagnosticCode.MISSING_ELEMENT_PROPERTY, "falta la propiedad options.")
            return ()
        raw = self._table["options"]
        if not isinstance(raw, list) or not all(isinstance(o, dict) for o in raw):
            self._problem(DiagnosticCode.INVALID_OPTIONS, "options debe ser una lista de tablas.")
            return ()
        if not 1 <= len(raw) <= MAX_OPTIONS:
            self._problem(
                DiagnosticCode.INVALID_OPTIONS, f"se admiten entre 1 y {MAX_OPTIONS} opciones."
            )
            return ()
        options: list[Option] = []
        values: set[str] = set()
        labels: set[str] = set()
        for index, option in enumerate(raw, start=1):
            for key in sorted(set(option) - {"value", "label"}):
                self._problem(
                    DiagnosticCode.INVALID_OPTIONS,
                    f"opción {index}: propiedad desconocida {safe_name(key)}.",
                )
            value, label = option.get("value"), _checked_label(option.get("label"))
            if not (
                isinstance(value, str)
                and len(value) <= OPTION_VALUE_MAX_LENGTH
                and OPTION_VALUE_RE.match(value)
            ):
                self._problem(
                    DiagnosticCode.INVALID_OPTIONS,
                    f"opción {index}: value inválido (a-z, 0-9, _ y -; máximo 64).",
                )
                continue
            if label is None:
                self._problem(DiagnosticCode.INVALID_OPTIONS, f"opción {index}: label inválido.")
                continue
            if value in values:
                self._problem(
                    DiagnosticCode.DUPLICATE_OPTION_VALUE, f"value {value} repetido en options."
                )
            if label in labels:
                self._problem(
                    DiagnosticCode.DUPLICATE_OPTION_LABEL, f"opción {index}: label repetido."
                )
            values.add(value)
            labels.add(label)
            options.append(Option(value, label))
        return tuple(options)


def _is_int64(value: object) -> bool:
    return type(value) is int and INT64_MIN <= value <= INT64_MAX


def _is_local_time(value: object) -> bool:
    return type(value) is time and value.tzinfo is None and value.microsecond == 0


def _is_offset_datetime(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.microsecond == 0
